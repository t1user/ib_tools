from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Optional

import eventkit as ev  # type: ignore
import ib_insync as ibi

from . import misc
from .base import Atom
from .blotter import Blotter
from .config import CONFIG
from .startup_routines import ErrorHandlers, OrderSyncStrategy, PositionSyncStrategy
from .state_machine import Strategy
from .trader import FakeTrader, Trader

log = logging.getLogger(__name__)


class Controller(Atom):
    """
    Intermediary between execution models (which are off ramps for
    strategies), :class:`Trader` and :class:`StateMachine`.  Use information
    provided by :class:`StateMachine` to make sure that positions held in
    the market reflect what is requested by strategies.

    """

    blotter: Optional[Blotter]
    config = CONFIG.get("controller") or {}

    def __init__(
        self,
        trader: Optional[Trader] = None,
    ):
        super().__init__()
        self.trader = trader or Trader(self.ib)
        # these are essential (non-optional) events
        self.ib.execDetailsEvent.connect(self.onExecDetailsEvent, self._log_event_error)
        self.ib.newOrderEvent.connect(self.onNewOrderEvent, self._log_event_error)
        self.ib.orderStatusEvent.connect(self.onOrderStatusEvent, self._log_event_error)
        # consider whether these are essential
        self.ib.orderStatusEvent.connect(self.log_order_status, self._log_event_error)
        self.ib.errorEvent.connect(self.log_error, self._log_event_error)

        self.set_hold()

        if self.config.get("use_blotter"):
            self.blotter = Blotter()
            self.ib.commissionReportEvent.connect(
                self.onCommissionReport, self._log_event_error
            )
        else:
            self.blotter = None

        if sync_frequency := self.config.get("sync_frequency"):
            self.sync_timer = ev.Timer(sync_frequency)
            self.sync_timer.connect(self.sync, error=self._log_event_error)

        if self.config.get("log_IB_events"):
            self._attach_logging_events()

        self.cold_start = CONFIG.get("coldstart")
        self.reset = CONFIG.get("reset")
        self.cancel_stray_orders = self.config.get("cancel_stray_orders")

        self.sync_handlers = ErrorHandlers(self.ib, self.sm, self)
        log.debug(f"Controller initiated: {self}")

    def _attach_logging_events(self):
        # these are non-essential events
        self.ib.newOrderEvent += self.log_new_order
        self.ib.cancelOrderEvent += self.log_cancel
        self.ib.orderModifyEvent += self.log_modification

    def set_hold(self) -> None:
        self.hold = True
        log.debug("hold set")

    def release_hold(self) -> None:
        if self.hold:
            self.hold = False
            log.debug("hold released")

    async def run(self) -> None:
        """
        Main entry point into the programme.  Ensure records up to
        date and any remaining initialization complete.
        """

        self.set_hold()

        if self.cold_start:
            log.debug("Starting cold... (state NOT read from db)")
        else:
            try:
                log.debug("Reading from store...")
                await self.sm.read_from_store()
                self.cold_start = True
            except Exception as e:
                log.exception(e)

        await self.sync()

        if self.reset:
            await self.execute_stops_and_close_positions()
            self.reset = False
            # zero-out all records
            self.sm.clear_models()

        # Only subsequently Streamers will run (I think...)

    async def sync(self, *args) -> None:
        log.debug("--- Sync ---")
        orders_report = OrderSyncStrategy.run(self.ib, self.sm)
        # IB events will be handled so that matched trades can be sent to blotter
        self.release_hold()
        await self.sync_handlers.handle_orders(orders_report)

        error_position_report = PositionSyncStrategy.run(self.ib, self.sm)
        await self.sync_handlers.handle_positions(error_position_report)

        log.debug("--- Sync completed ---")

    async def onData(self, data, *args) -> None:
        """
        After obtaining transaction details from execution model,
        verify if the intended effect is the same as achieved effect.
        """
        super().onData(data)
        if not (delay := self.config.get("execution_verification_delay")):
            return

        try:
            strategy = data["strategy"]
            amount = data["amount"]
            target_position = data["target_position"]
            await asyncio.sleep(delay)
            self.verify_transaction_integrity(strategy, amount, target_position)
        except KeyError:
            log.exception(
                "Unable to verify transaction integrity", extra={"data": data}
            )

    def trade(
        self,
        strategy: str,
        contract: ibi.Contract,
        order: ibi.Order,
        action: str,
        data: Strategy,
    ) -> ibi.Trade:
        trade = self.trader.trade(contract, order)
        self.sm.register_order(strategy, action, trade, data)
        trade.filledEvent += partial(self.log_trade, reason=action, strategy=strategy)
        return trade

    def cancel(self, trade: ibi.Trade) -> Optional[ibi.Trade]:
        return self.trader.cancel(trade)

    async def onNewOrderEvent(self, trade: ibi.Trade) -> None:
        """
        Check if the system knows about the order that was just posted
        to the broker.

        This is an event handler (callback).  Connected (subscribed)
        to :meth:`ibi.IB.newOrderEvent` in :meth:`__init__`
        """
        # Consider whether essential or optional
        # Maybe some order verification here?
        log.debug(f"New order event: {trade.order.orderId, trade.order.permId}")
        if not (trade.order.orderId < 0 or self.sm.order.get(trade.order.orderId)):
            log.critical(
                f"Unknown trade in the system {trade.order} {trade.contract.symbol}"
            )

    async def onOrderStatusEvent(self, trade: ibi.Trade) -> None:
        if self.hold:
            return

        # this will create new order record if it doesn't already exist
        await self.sm.save_order_status(trade)

    def register_position(
        self, strategy_str: str, strategy: Strategy, trade: ibi.Trade, fill: ibi.Fill
    ) -> None:
        try:
            if fill.execution.side == "BOT":
                strategy.position += fill.execution.shares
                log.debug(
                    f"Registered orderId: {trade.order.orderId} permId: "
                    f"{trade.order.permId} BUY {trade.order.orderType} "
                    f"for {strategy_str} --> position: {strategy.position}"
                )
            elif fill.execution.side == "SLD":
                strategy.position -= fill.execution.shares
                log.debug(
                    f"Registered orderId {trade.order.orderId} permId: "
                    f"{trade.order.permId} SELL {trade.order.orderType} "
                    f"for {strategy_str} --> position: {strategy.position}"
                )
            else:
                log.critical(
                    f"Abiguous fill: {fill} for order: {trade.order} for "
                    f"{trade.contract.localSymbol} strategy: {strategy}"
                )
        except Exception as e:
            log.exception(e)

    def _cleanup_obsolete_orders(self, strategy: Strategy) -> None:
        """Delete stop/take-profit/close orders for a strategy that has no position."""
        order_infos = list(self.sm.orders_for_strategy(strategy.strategy))
        for oi in order_infos:
            if (oi.action != "OPEN") and oi.active:
                log.debug(f"Resting order cleanup: {oi.action, oi.trade.order.orderId}")
                self.trader.cancel(oi.trade)

    async def onExecDetailsEvent(self, trade: ibi.Trade, fill: ibi.Fill) -> None:
        """
        Register position.
        """
        strategy = (
            self.assign_manual_trade(trade)
            or self.sm.strategy_for_trade(trade)
            or self.assign_unknown_trade(trade)
        )
        self.register_position(strategy.strategy, strategy, trade, fill)

        # await asyncio.sleep(1)
        # try:
        #     if (strategy.position == 0) & (self.cancel_stray_orders) & trade.isDone():
        #         self._cleanup_obsolete_orders(strategy)
        # except Exception as e:
        #     log.exception(e)

    def onCommissionReport(
        self, trade: ibi.Trade, fill: ibi.Fill, report: ibi.CommissionReport
    ) -> None:
        """
        Writing commission on :class:`ibi.Trade` is the final stage of
        order execution.  After that trade object is ready for storing
        in blotter.
        """

        # silence emission of all all orders from session on startup
        if self.hold:
            return

        data = self.sm.order.get(trade.order.orderId)
        if data:
            strategy, action, _, params, _ = data
            position_id = params.get("position_id")

            kwargs = {
                "strategy": strategy,
                "action": action,
                "position_id": position_id,
                "params": ibi.util.tree(params),
            }

            if arrival_price := params.get("arrival_price"):
                kwargs.update(
                    {
                        "price_time": arrival_price["time"],
                        "bid": arrival_price["bid"],
                        "ask": arrival_price["ask"],
                    }
                )

        elif trade.order.totalQuantity == 0:
            return

        assert self.blotter is not None
        self.blotter.log_commission(trade, fill, report, **kwargs)

    def verify_transaction_integrity(
        self,
        strategy: str,
        amount: float,  # amount in transaction being verified
        target_position: float,  # total resulting position
    ) -> None:
        """
        Called by :meth:`onData`, which is passing data that was the
        basis for transaction.  The purpose of this method is to
        confirm that the resulting transaction achieved required
        objectives.  Things vefied are: 1.  actual resulting position
        in broker records 2.  records in state_machine

        Any errors are logged but not corrected (maybe changed in
        future).
        """
        data = self.sm.strategy.get(strategy)
        if data:
            records_ok = data.position == target_position
            if records_ok:
                log.debug(f"{strategy} position OK? -> {records_ok} <- ")
            else:
                log.error(
                    f"Wrong position for {strategy} - "
                    f"target: {target_position}, position: {data.position}"
                )

            contract = data.active_.symbol
            sm_position = self.sm.position.get(contract, 0.0)
            ib_position = self.trader.position_for_contract(contract)
            position_ok = sm_position == ib_position
            if position_ok:
                log.debug(f"{contract} position OK? -> {position_ok} <-")
            else:
                log.error(
                    f"Wrong position for {contract} - " f"{ib_position=}, {sm_position}"
                )
        else:
            log.critical(f"Attempt to trade for unknown strategy: {strategy}")

    def _assign_trade(self, trade: ibi.Trade) -> Optional[Strategy]:

        # assumed unknown trade is to close a position
        active_strategies_list = [
            s
            for s in self.sm.for_contract[trade.contract]
            if self.sm.strategy[s].active
        ]
        log.debug(
            f"Attemp to assign unknown trade to a strategy: "
            f"{active_strategies_list}"
        )

        if len(active_strategies_list) == 1:
            strategy_str = active_strategies_list[0]
            strategy = self.sm.strategy[strategy_str]

        # if more than 1 active, unknown trade is for the one without
        # resting orders (resting orders are most likely stop-losses)
        elif candidate_strategies := [
            s for s in active_strategies_list if self.sm.orders_for_strategy(s)
        ]:
            log.debug(
                f"Active strategies without resting orders: " f"{candidate_strategies}"
            )
            # if more than one just pick first one
            # there's no way to determine which strategy was meant
            if candidate_strategies:
                strategy_str = candidate_strategies[0]
                strategy = self.sm.strategy[strategy_str]
        else:
            strategy = None

        return strategy

    def _make_strategy(self, trade: ibi.Trade, description: str) -> Strategy:
        """
        Last resort when strategy cannot be matched.  Creating new
        made up strategy to make sure that position change resulting
        from trade will be somehow accounted for.
        """
        strategy_str = f"{description}_{trade.contract.symbol}"
        strategy = self.sm.strategy[strategy_str]  # this creates new Strategy
        strategy["active_contract"] = trade.contract
        return strategy

    def assign_manual_trade(self, trade: ibi.Trade) -> Optional[Strategy]:

        if trade.order.orderId >= 0:
            return None

        strategy = self._assign_trade(trade) or self._make_strategy(
            trade, "manual_strategy"
        )
        log.debug(f"Manual trade assigned to strategy {strategy}.")

        # this will save strategy on OrderInfo
        self.sm.update_strategy_on_order(trade.order.orderId, strategy.strategy)

        return strategy

    def assign_unknown_trade(self, trade: ibi.Trade) -> Strategy:
        strategy = self._assign_trade(trade) or self._make_strategy(trade, "unknown")
        log.critical(f"Unknow trade: {trade}")

        # this will save strategy on OrderInfo
        self.sm.update_strategy_on_order(trade.order.orderId, strategy.strategy)

        return strategy

    def log_order_status(self, trade: ibi.Trade) -> None:
        # Connected to onOrderStatusEvent

        if self.hold:
            return

        if trade.order.orderId < 0:
            log.warning(
                f"Manual trade: {trade.order} status update: {trade.orderStatus}"
            )

        elif trade.isDone():
            log.debug(
                f"{trade.contract.symbol}: order {trade.order.orderId} "
                f"{trade.order.orderType} done {trade.orderStatus.status}."
            )
        else:
            log.info(
                f"{trade.contract.symbol}: OrderStatus ->{trade.orderStatus.status}<-"
                f" for order: {trade.order},"
            )

    @staticmethod
    def log_new_order(trade: ibi.Trade) -> None:
        log.debug(f"New order {trade.order} for {trade.contract.localSymbol}")

    @staticmethod
    def log_trade(trade: ibi.Trade, reason: str = "", strategy: str = "") -> None:
        log.info(
            f"{reason} trade filled: {trade.contract.localSymbol} "
            f"{trade.order.action} {trade.filled()}"
            f"@{misc.trade_fill_price(trade)} --> {strategy} "
            f"orderId: {trade.order.orderId}, permId: {trade.order.permId}"
        )

    @staticmethod
    def log_cancel(trade: ibi.Trade) -> None:
        log.info(
            f"{trade.order.orderType} order {trade.order.action} "
            f"{trade.remaining()} (of "
            f"{trade.order.totalQuantity}) for "
            f"{trade.contract.localSymbol} cancelled"
        )

    @staticmethod
    def log_modification(trade: ibi.Trade) -> None:
        log.debug(f"Order modified: {trade.order}")

    def log_error(
        self, reqId: int, errorCode: int, errorString: str, contract: ibi.Contract
    ) -> None:
        # Connected to ib.errorEvent

        if errorCode < 400:
            # reqId is most likely orderId
            # order rejected is errorCode = 201
            # 421: Error validating request.-'bN' : cause - Missing order exchange
            order_info = self.sm.order.get(reqId)
            if order_info:
                (strategy, action, trade) = order_info
                order = trade.order
            else:
                strategy, action, trade, order = "", "", "", ""

            log.error(
                f"Error {errorCode}: {errorString} {contract}, "
                f"{strategy} | {action} | {order}"
            )

    def handle_rejected_order(self, trade: ibi.Trade) -> None:
        # NOT IN USE
        oi = self.sm.order.get(trade.order.orderId)
        if oi:
            log.error(
                f"Rejected order {trade.order.orderId} {trade.order.action} "
                f"{oi.action} for {oi.strategy}"
            )
        else:
            log.error(f"No records for rejected order: {trade.order.orderId}")

    async def execute_stops_and_close_positions(self) -> None:
        await Terminator(self).run()

    def close_positions(self) -> None:
        positions: list[ibi.Position] = self.ib.positions()
        for position in positions:
            self.ib.qualifyContracts(position.contract)
            self.ib.placeOrder(
                position.contract,
                ibi.MarketOrder(
                    "BUY" if position.position < 0 else "SELL", abs(position.position)
                ),
            )

    def nuke(self) -> None:
        """
        Cancel all open orders, close existing positions and prevent
        any further trading.  Response to a critical error or request
        sent by administrator.

        ---> Currently not in use. <---
        """
        # this will ignore any further orders coming from the system
        # don't use self.trader any more
        self.trader = FakeTrader(self.ib)
        self.ib.reqGlobalCancel()
        self.close_positions()

        log.critical("Self nuked!!!!! No more trades will be executed until restart.")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.sm, self.ib, self.blotter})"


class Terminator:
    def __init__(self, controller: Controller):
        log.warning("TERMINATOR in action.")
        self.controller = controller
        self.trades = []
        self.trades = controller.ib.openTrades()
        self.positions = controller.trader.positions()

    async def run(self):
        self.cancel_orders()
        await self.controller.ib.qualifyContractsAsync(*self.positions.keys())
        self.close_positions()
        if positions := await self.report():
            log.debug(f"Unclosed positions: {positions}")
            log.debug("Going nuclear...")
            self.controller.ib.reqGlobalCancel()
            self.controller.close_positions()
        log.debug("Closed all positions.")

    def register_trade(self, trade: ibi.Trade) -> None:
        trade.filledEvent += self.trades.remove
        trade.cancelledEvent += self.trades.remove
        trade.cancelledEvent += lambda x: log.error(f"Rejected trade: {x}")

    @staticmethod
    def describe_trade(t: ibi.Trade) -> tuple[str, str, float, int]:
        return (
            t.contract.symbol,
            t.order.action,
            t.order.totalQuantity,
            t.order.orderId,
        )

    def _strategy_trade(self, strategy, contract, action, amount):
        new_trade = self.controller.trade(
            strategy.strategy,
            contract,
            ibi.MarketOrder(action, amount),
            "RESET",
            strategy,
        )
        self.register_trade(new_trade)
        return new_trade

    def cancel_orders(self):
        log.debug(
            f"Will attempt to cancel orders: "
            f"{[self.describe_trade(t) for t in self.trades]}"
        )

        for trade in self.trades:
            log.debug(f"handling order: {trade.order}")
            if trade.order.orderType in ("STP", "TRAIL"):
                # Make sure no orders executed if there's no corresponding position
                stop_amount = trade.remaining() if trade.order.action == "BUY" else -1
                existing_amount = self.positions.get(trade.contract, 0)

                if existing_amount and (
                    misc.sign(stop_amount) == misc.sign(existing_amount)
                ):
                    trade_amount = existing_amount - stop_amount
                    strategy = self.controller.sm.strategy_for_trade(trade)
                    trade.cancelledEvent += partial(
                        self._strategy_trade,
                        strategy=strategy,
                        contract=trade.contract,
                        action=trade.order.action,
                        amount=abs(trade_amount),
                    )
                    self.controller.cancel(trade)

                    try:
                        self.positions[trade.contract] -= trade_amount
                    except KeyError:
                        pass
                    continue
            self.controller.cancel(trade)

    def close_positions(self):
        log.debug(
            f"Will attempt to close existing positions: "
            f"{ {c.symbol: p for c, p in self.positions.items()} }"
        )

        for contract, position in self.positions.items():
            if position:
                # Again make sure total orders issued match existing positions
                self.register_trade(
                    self.controller.trader.trade(
                        contract,
                        ibi.MarketOrder(
                            "BUY" if position < 0 else "SELL",
                            abs(position),
                            tif="DAY",
                            outsideRth=True,
                        ),
                    )
                )

    async def report(self):
        n = 0
        while not all([t.isDone() for t in self.trades]):
            log.warning(
                f"Closing positions in progress: "
                f"{[self.describe_trade(t) for t in self.trades]}"
            )
            await asyncio.sleep(1)
            if (n := n + 1) > 10:
                break
        return self.trades
