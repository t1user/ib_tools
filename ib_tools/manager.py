from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, cast

import ib_insync as ibi

from ib_tools import misc
from ib_tools.base import Atom
from ib_tools.controller import Controller

# from ib_tools.runner import App
from ib_tools.state_machine import StateMachine
from ib_tools.streamers import Streamer

log = logging.getLogger(__name__)


@dataclass
class InitData:
    ib: ibi.IB
    contract_list: list[ibi.Contract]
    contract_details: dict[ibi.Contract, ibi.ContractDetails] = field(
        default_factory=dict
    )
    trading_hours: dict[ibi.Contract, list[tuple[datetime, datetime]]] = field(
        default_factory=dict
    )

    async def __call__(self) -> "InitData":
        await self.qualify_contracts()
        await self.acquire_contract_details()
        self.process_trading_hours()
        return self

    async def qualify_contracts(self) -> "InitData":
        await self.ib.qualifyContractsAsync(*self.contract_list)
        log.debug(f"contracts qualified {set([c.symbol for c in self.contract_list])}")
        return self

    async def acquire_contract_details(self) -> "InitData":
        for contract in set(self.contract_list):
            log.debug(f"Acquiring details for: {contract.symbol}")
            details_ = await IB.reqContractDetailsAsync(contract)
            try:
                assert len(details_) == 1
            except AssertionError:
                log.exception(f"Ambiguous contract: {contract}. Critical error.")

            details = details_[0]
            self.contract_details[cast(ibi.Contract, details.contract)] = details
        log.debug(
            f"Details acquired: {set([k.symbol for k in self.contract_details.keys()])}"
        )
        return self

    _process_trading_hours = staticmethod(misc.process_trading_hours)

    def process_trading_hours(self) -> "InitData":
        for contract, details in self.contract_details.items():
            self.trading_hours[contract] = self._process_trading_hours(
                details.tradingHours, details.timeZoneId
            )
        log.debug(
            f"Trading hours processed for: "
            f"{[c.symbol for c in self.trading_hours.keys()]}"
        )
        return self


class Jobs:
    _tasks: set = set()

    def __init__(self, init_data: InitData):
        self.init_data = init_data
        self.streamers = Streamer.instances

    def _handle_error(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception(e)

    async def __call__(self):
        await self.init_data()

        log.info(
            f"Open positions on restart: "
            f"{ {p.contract.symbol: p.position for p in IB.positions()} }"
        )
        order_dict = {
            t.contract.symbol: (
                t.order.orderId,
                t.order.orderType,
                t.order.action,
                t.order.totalQuantity,
            )
            for t in IB.openTrades()
        }
        log.info(f"Orders on restart: {order_dict}")

        for streamer in self.streamers:
            task = asyncio.create_task(streamer.run(), name=f"{streamer!s}, ")
            log.debug(f"Task created: {task}")

            # Add task to the set. This creates a strong reference.
            self._tasks.add(task)

            # To prevent keeping references to finished tasks forever,
            # make each task remove its own reference from the set after
            # completion:
            task.add_done_callback(self._tasks.discard)
            # ensure errors are logged for debugging
            task.add_done_callback(self._handle_error)
        await asyncio.gather(*self._tasks, return_exceptions=False)


IB: Final[ibi.IB] = ibi.IB()
STATE_MACHINE: Final[StateMachine] = StateMachine()
CONTROLLER: Final[Controller] = Controller(STATE_MACHINE, IB)
INIT_DATA = InitData(IB, Atom.contracts)
JOBS = Jobs(INIT_DATA)
Atom.set_init_data(INIT_DATA)
