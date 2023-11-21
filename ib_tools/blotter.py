from __future__ import annotations

import csv
import logging
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

# import motor.motor_asyncio  # type: ignore
from arctic import TICK_STORE, Arctic  # type: ignore
from ib_insync import util
from ib_insync.objects import CommissionReport, Fill
from ib_insync.order import Trade
from pymongo import MongoClient  # type: ignore

from ib_tools.utilities import default_path

log = logging.getLogger(__name__)


class AbstractBaseBlotter(ABC):

    """
    Api for storing blotters.

    Log trade only after all commission reports arrive. Trader
    will log commission after every commission event. It's up to blotter
    to parse through those reports, determine when the trade is ready
    to be logged and filter out some known issues with ib-insync reports.

    Blotter works in one of two modes:
    - trade by trades save to store: suitable for live trading
    - save to store only full blotter: suitable for backtest (save time
      on i/o)
    """

    def __init__(self, save_immediately: bool = True) -> None:
        self.save_immediately = save_immediately
        self.blotter: list[dict] = []
        self.unsaved_trades: dict = {}
        self.com_reports: dict = {}

    def log_trade(self, trade: Trade, comms: list[CommissionReport], **kwargs) -> None:
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

        if kwargs:
            row.update(kwargs)
        self.save_report(row)
        log.debug(f"trade report saved: {row['order_id'], row['side'], row['symbol']}")

    def log_commission(
        self, trade: Trade, fill: Fill, comm_report: CommissionReport, **kwargs
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
            self.write_to_file(report)
        else:
            self.blotter.append(report)

    @abstractmethod
    def write_to_file(self, data: dict[str, Any]) -> None:
        """
        Write single line of data to the store.
        """
        pass

    @abstractmethod
    def save(self) -> None:
        """
        Write full blotter (all rows) to store.
        """
        pass

    @abstractmethod
    def delete(self, query: dict) -> str:
        """
        Delete items from blotter.
        """
        pass

    @abstractmethod
    def clear(self):
        """
        Clear all items in the blotter.
        """
        s = input(
            "This will permanently delete all items in the blotter. " "Continue? "
        ).lower()
        if s != "yes" and s != "y":
            sys.exit()

    def __repr__(self):
        return (
            f"{self.__class__.__name__}"
            + "("
            + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])
            + ")"
        )


class CsvBlotter(AbstractBaseBlotter):
    fieldnames: list[str] = []

    def __init__(
        self,
        save_immediately: bool = True,
        filename: Optional[str] = None,
        path: Optional[str] = None,
        note: str = "",
    ):
        if path is None:
            path = default_path("blotter")
        if filename is None:
            filename = __file__.split("/")[-1][:-3]
        self.file = (
            f"{path}/{filename}_"
            f'{datetime.today().strftime("%Y-%m-%d_%H-%M")}{note}.csv'
        )
        super().__init__(save_immediately)

    def create_header(self) -> None:
        with open(self.file, "w") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writeheader()

    def write_to_file(self, data: dict[str, Any]) -> None:
        if not self.fieldnames:
            self.fieldnames = list(data.keys())
            self.create_header()
        with open(self.file, "a") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(data)

    def save(self) -> None:
        self.fieldnames = list(self.blotter[0].keys())
        self.create_header()
        with open(self.file, "a") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            for item in self.blotter:
                writer.writerow(item)

    def delete(self, query: dict) -> str:
        raise NotImplementedError

    def clear(self) -> str:
        raise NotImplementedError


class MongoBlotter(AbstractBaseBlotter):
    def __init__(
        self,
        save_immediately: bool = True,
        host: str = "localhost",
        port: int = 27017,
        db: str = "blotter",
        collection: "str" = "test_blotter",
    ) -> None:
        self.client = MongoClient(host, port)
        self.db = self.client[db]
        self.collection = self.db[collection]
        super().__init__(save_immediately)

    def write_to_file(self, data: dict[str, Any]) -> None:
        self.collection.insert_one(data)

    def save(self) -> None:
        self.collection.insert_many(self.blotter)

    def read(self) -> pd.DataFrame:
        return util.df([i for i in self.collection.find()])

    def delete(self, querry: dict) -> str:
        results = self.collection.find(querry)
        for doc in results:
            print(doc)
        s = input("Above documents will be deleted." "Continue? ").lower()
        if s != "yes" and s != "y":
            sys.exit()
        x = self.collection.delete_many(querry)
        return f"Documents deleted: {x.raw_result}"

    def clear(self) -> str:
        print(f"Deleting all items from {self.collection}")
        super().clear()
        x = self.collection.delete_many({})
        return f"Deleted {x.deleted_count} documents."

    # class AsyncMongoBlottter(AbstractBaseBlotter):
    #     """
    #     NOT TESTED. Clear and delete methods missing. TODO.
    #     """

    #     def __init__(
    #         self,
    #         save_immediately: bool = True,
    #         host: str = "localhost",
    #         port: int = 27017,
    #         db: str = "blotter",
    #         collection: "str" = "test_blotter",
    #     ) -> None:
    #         self.client = motor.motor_asyncio.AsyncIOMotorClient(host, port)
    #         self.db = self.client[db]
    #         self.collection = self.db[collection]
    #         super().__init__(save_immediately)
    #
    # async def _write_to_file(self, data: dict[str, Any]) -> None:
    #     await self.collection.insert_one(data)

    # def write_to_file(self, data: dict[str, Any]) -> None:
    #     util.run(self._write_to_file(data))

    # async def _save(self) -> None:
    #     await self.collection.insert_many(self.blotter)

    # def save(self) -> None:
    #     util.run(self._save())


class TickBlotter(AbstractBaseBlotter):
    def __init__(
        self,
        save_immediately: bool = True,
        host: str = "localhost",
        library: str = "tick_blotter",
        collection: str = "test_blotter",
    ) -> None:
        self.db = Arctic(host)
        self.db.initialize_library(library, lib_type=TICK_STORE)
        self.store = self.db[library]
        self.collection = collection

    def write_to_file(self, data: dict[str, Any]) -> None:
        data["index"] = pd.to_datetime(data["time"], utc=True)
        self.store.write(self.collection, [data])

    def save(self) -> None:
        data = []
        for d in self.blotter:
            d.update({"index": pd.to_datetime(d["time"], utc=True)})
            data.append(d)
        self.store.write(self.collection, data)

    def delete(self, querry: dict) -> str:
        raise NotImplementedError

    def clear(self) -> str:
        raise NotImplementedError
