import asyncio
from ib_insync import util
from logbook import ERROR, INFO, WARNING

from backtester import IB, DataSourceManager, Market
from logger import logger
from datastore import ArcticStore
from saver import PickleSaver
from blotter import CsvBlotter
from manager import Manager
from trader import Trader
from execution_models import EventDrivenExecModel
from test_strategy import strategy_kwargs


log = logger(__file__[:-3], WARNING, WARNING)

start_date = '20200101'
end_date = '20200831'
cash = 120000
store = ArcticStore('TRADES_30_secs')
source = DataSourceManager(store, start_date, end_date)
ib = IB(source, mode='db_only', index=-1)  # mode is: 'db_only' or 'use_ib'

util.logToConsole()
asyncio.get_event_loop().set_debug(True)

blotter = CsvBlotter(save_to_file=False, filename='backtest', path='backtests',
                     note=f'_{start_date}_{end_date}')
saver = PickleSaver('notebooks/freeze/backtest')
trader = Trader(ib, blotter)
exec_model = EventDrivenExecModel(trader)
manager = Manager(ib, saver=saver, exec_model=exec_model, **strategy_kwargs)
market = Market(cash, manager, reboot=False)
ib.run()
blotter.save()
manager.freeze()
