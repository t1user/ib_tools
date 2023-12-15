from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import ib_insync as ibi

from ib_tools.saver import CsvSaver, SaveManager

log = logging.getLogger(__name__)


BLOTTER_SAVER = CsvSaver(
    folder="blotter", note="blotter"
)  # TODO: this has to be read from CONFIG


class Blotter:

    """
    Log trade only after all commission reports arrive. Trader
    will log commission after every commission event. It's up to blotter
    to parse through those reports, determine when the trade is ready
    to be logged and filter out some known issues with ib-insync reports.

    Blotter works in one of two modes:
    - trade by trades save to store: suitable for live trading
    - save to store only full blotter: suitable for backtest (save time
      on i/o)
    """

    save = SaveManager(BLOTTER_SAVER)

    def __init__(self, save_immediately: bool = True) -> None:
        self.save_immediately = save_immediately
        self.blotter: list[dict] = []
        self.unsaved_trades: dict = {}
        self.com_reports: dict = {}

    def log_trade(
        self, trade: ibi.Trade, comms: list[ibi.CommissionReport], **kwargs
    ) -> None:
        row = {
            "local_time": datetime.now(),
            "sys_time": datetime.now(timezone.utc),  # system time
            "last_fill_time": trade.log[-1].time,
            "contract": trade.contract.localSymbol,  # 4 letter symbol string
            "symbol": trade.contract.symbol,
            "side": trade.order.action,  # buy or sell
            "order_type": trade.order.orderType,  # order type
            "order_price": trade.order.auxPrice,  # order price
            "amount": trade.orderStatus.filled,  # unsigned amount
            "price": trade.orderStatus.avgFillPrice,
            "order_id": trade.order.orderId,  # non unique
            "perm_id": trade.order.permId,  # unique trade id
            "commission": sum([comm.commission for comm in comms]),
            "realizedPNL": sum([comm.realizedPNL for comm in comms]),
            "fills": [fill.execution.dict() for fill in trade.fills],  # type: ignore
        }
        row["trade"] = ibi.util.tree(trade)
        if kwargs:
            row.update(kwargs)
        self.save_report(row)
        log.debug(
            f"trade report will be  saved to blotter: "
            f"{row['order_id'], row['side'], row['symbol']}"
        )

    def log_commission(
        self,
        trade: ibi.Trade,
        fill: ibi.Fill,
        comm_report: ibi.CommissionReport,
        **kwargs,
    ):
        """
        Get trades that have all CommissionReport filled and log them.
        """
        # bug in ib_insync sometimes causes trade to have fills for
        # unrelated transactions, permId uniquely identifies order
        comms = [
            fill.commissionReport
            for fill in trade.fills
            if fill.commissionReport.execId != ""
            and fill.execution.permId == trade.order.permId
        ]
        fills = [
            fill for fill in trade.fills if fill.execution.permId == trade.order.permId
        ]
        if trade.isDone() and (len(comms) == len(fills)):
            self.log_trade(trade, comms, **kwargs)

    def save_report(self, report: dict[str, Any]) -> None:
        """
        Choose whether row of data (report) should be written to permanent
        store immediately or just kept in self.blotter for later.
        """
        if self.save_immediately:
            self.save(report)
        else:
            self.blotter.append(report)

    def save_many(self) -> None:
        """
        Write full blotter (all rows) to store.
        """
        BLOTTER_SAVER.save_many(self.blotter)

    def __repr__(self):
        return f"Blotter(save_immediately={self.save_immediately})"
