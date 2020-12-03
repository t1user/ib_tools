import asyncio
from ib_insync import util
from logbook import ERROR, INFO, WARNING

from backtester import IB, DataSourceManager, Market
from logger import logger
from datastore import ArcticStore
from saver import PickleSaver
from blotter import CsvBlotter
from manager import Manager
from test_strategy import strategy_kwargs


log = logger(__file__[:-3], WARNING, WARNING)

start_date = '20180601'
end_date = '20191231'
cash = 80000
store = ArcticStore('TRADES_30_secs')
source = DataSourceManager(store, start_date, end_date)
ib = IB(source, mode='db_only', index=-2)  # mode is: 'db_only' or 'use_ib'

util.logToConsole()
asyncio.get_event_loop().set_debug(True)

blotter = CsvBlotter(save_to_file=False, filename='backtest', path='backtests',
                     note=f'_{start_date}_{end_date}_eq_weighted_no_gc')
saver = PickleSaver('notebooks/freeze/backtest')
manager = Manager(ib, saver=saver, blotter=blotter, **strategy_kwargs)
market = Market(cash, manager, reboot=False)
ib.run()
