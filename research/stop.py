import pandas as pd  # type: ignore
import numpy as np  # type: ignore
from typing import (Optional, Union, Literal, Tuple, Type, TypeVar, Dict, Any)
from abc import ABC, abstractmethod

from signal_converters import pos_trans
from vector_backtester import get_min_tick

# ## Stop loss ###

StopMode = Literal['fixed', 'trail']


class BaseBracket(ABC):

    def __init__(self, distance: float, transaction: int,
                 entry: float = 0) -> None:
        self.distance = distance
        self.position = transaction
        self.entry = entry
        self.trigger = self.set_trigger()
        # print(f'bracket init: {self}, e: {entry}')

    @abstractmethod
    def evaluate(self, high: float, low: float) -> float:
        """
        Bracket has been triggered?
        True: return price to execute transaction
        False: return 0
        """
        pass

    def set_trigger(self, *args: Any) -> float:
        """
        This is for stop loss.  For take profit the method has to be
        overridden.
        """
        return self.entry - self.distance * self.position

    def __repr__(self):
        return (f'{self.__class__.__name__}' + '(' + ', '.join(
            [f'{k}={v}' for k, v in self.__dict__.items()]) + ')')


class TrailStop(BaseBracket):

    def evaluate(self, high: float, low: float) -> float:
        if self.position == -1:
            if self.trigger <= high:
                return self.trigger
            else:
                self.trigger = min(self.trigger, low + self.distance)
                return 0
        elif self.position == 1:
            if self.trigger >= low:
                return self.trigger
            else:
                self.trigger = max(self.trigger, high - self.distance)
                return 0
        else:
            raise ValueError(
                f'Evaluating TrailStop for zero position. '
                f'Position: {self.position}')


class FixedStop(BaseBracket):

    def evaluate(self, high: float, low: float) -> float:
        if self.position == 1 and self.trigger >= low:
            return self.trigger
        elif self.position == -1 and self.trigger <= high:
            return self.trigger
        else:
            return 0


class TakeProfit(BaseBracket):

    multiple: float

    @classmethod
    def set_up(cls, multiple: float) -> Type[BaseBracket]:
        cls.multiple = multiple
        return cls

    def evaluate(self, high: float, low: float) -> float:
        if self.position == -1 and self.trigger >= low:
            return self.trigger
        elif self.position == 1 and self.trigger <= high:
            return self.trigger
        else:
            return 0

    def set_trigger(self, *args: Any) -> float:
        return self.entry + self.distance * self.position * self.multiple


class NoTakeProfit(BaseBracket):

    def __init__(self, *args):
        pass

    def evaluate(self, high: float, low: float) -> bool:
        return False


stop_dict: Dict[StopMode, Type[BaseBracket]] = {
    'fixed': FixedStop, 'trail': TrailStop}

A = TypeVar('A', bound='Adjust')


class Adjust:

    adjusted_stop: Type[BaseBracket]
    trigger_multiple: float
    stop_multiple: float

    def __init__(self, stop_distance: float,  transaction: int,
                 entry: float = 0) -> None:
        self.entry = entry
        self.adjusted_stop_distance = stop_distance * self.stop_multiple
        self.adjusted_trigger_distance = stop_distance * self.trigger_multiple
        self.position = transaction
        self.set_trigger()
        self.done = False
        # print(f'Adjust init: {self}')

    @classmethod
    def set_up(cls: Type[A], adjusted_stop: Type[BaseBracket],
               trigger_multiple: float, stop_multiple: float) -> Type[A]:
        cls.adjusted_stop = adjusted_stop
        cls.trigger_multiple = trigger_multiple
        cls.stop_multiple = stop_multiple
        return cls

    def evaluate(self, order: BaseBracket, high: float, low: float
                 ) -> BaseBracket:
        """
        Verify whether stop should be adjusted, return correct stop
        (adjusted or not).

        """
        if self.done:
            return order
        elif ((self.position == -1 and self.trigger >= low)
                or (self.position == 1 and self.trigger <= high)):

            adjusted = self.adjusted_stop(
                self.adjusted_stop_distance, order.position,
                entry=self.trigger)
            # print(f'Adjusted: {order} to {adjusted} at h: {high}, l: {low}')
            self.done = True
            return adjusted
        else:
            return order

    def set_trigger(self) -> None:
        self.trigger = (self.entry + self.adjusted_trigger_distance
                        * self.position)

    def __repr__(self):
        return (f'{self.__class__.__name__}' + '(' + ', '.join(
            [f'{k}={v}' for k, v in self.__dict__.items()]) + ')')


class NoAdjust(Adjust):
    def __init__(self, *args):
        pass

    def evaluate(self, order: BaseBracket, *args) -> BaseBracket:
        return order


class Context:

    def __init__(self, stop: Type[BaseBracket], tp: Type[BaseBracket],
                 adjust: Type[Adjust], always_on: bool = True
                 ) -> None:
        """
        always_on - whether the system attempts to always be in the
        market, True means that closing transaction for a position is
        simultaneusly a transaction to open opposite position, False
        means that closing transaction for a position results in
        system being out of the market.  Triggering brackets doesn't
        mean openning opposite position (that requires a transaction
        opposite to current position).
        """

        self._stop = stop
        self._tp = tp
        self._adjust = adjust
        self.always_on = always_on
        self.position = 0
        # print(f'Context init: {self}')

    def __call__(self, row: np.array) -> Tuple[int, float]:
        self.transaction = row[0]
        self.high = row[1]
        self.low = row[2]
        self.distance = row[3]
        self.price = row[4]
        return self.dispatch()

    def dispatch(self) -> Tuple[int, float]:
        if self.position:
            self.eval_for_close()
        else:
            self.eval_for_open()
        return (self.position, self.price)

    def eval_for_close(self) -> None:
        if self.transaction == -self.position:
            # print(
            #    f'Close transaction: {self.transaction}, h: {self.high} l: {self.low}')
            self.close_position()
            if self.always_on:
                self.open_position()
        else:
            self.eval_brackets()

    def eval_for_open(self) -> None:
        if self.transaction:
            self.open_position()

    def open_position(self) -> None:
        self.stop = self._stop(self.distance, self.transaction,
                               self.price)
        self.tp = self._tp(self.distance, self.transaction,
                           self.price)
        self.adjust = self._adjust(self.distance, self.transaction,
                                   self.price)
        self.position = self.transaction
        # position may be closed on the same bar, where it's open
        self.eval_brackets()

    def close_position(self) -> None:
        self.position = 0
        # print('---------------------')

    def eval_brackets(self) -> None:
        if (p := self.stop.evaluate(self.high, self.low)):
            # print(f'stop hit: {self.stop}, h: {self.high}, l: {self.low}')
            self.price = p
            self.close_position()
            return
        elif (p := self.tp.evaluate(self.high, self.low)):
            # print(f'tp hit: {self.tp}, h: {self.high}, l: {self.low}')
            self.price = p
            self.close_position()
            return
        else:
            self.eval_adjust()

    def eval_adjust(self) -> None:
        self.stop = self.adjust.evaluate(self.stop, self.high, self.low)

    def __repr__(self):
        return (f'{self.__class__.__name__}' + '(' + ', '.join(
            [f'{k}={v}' for k, v in self.__dict__.items()]) + ')')


def _stop_loss(data: np.array, stop: Context) -> np.array:
    """
    Args:
    -----

    data: collumns have the folowing meaning:

    0 - transaction is -1, 1 or 0 for transaction signal

    1 - high price for the price bar

    2 - low price for the price bar

    3 - stop distance (if stop were to be applied at this point)
    """

    position = np.zeros((data.shape[0], 1), dtype=np.int8)
    price = np.zeros((data.shape[0], 1), dtype=np.float32)
    for i, row in enumerate(data):
        position[i], price[i] = stop(row)
    return np.concatenate((position, price), axis=1)


def param_factory(mode: StopMode, tp_multiple: Optional[float] = None,
                  adjust_tuple: Optional[Tuple[StopMode, float, float]] = None
                  ) -> Tuple[Type[BaseBracket], Type[BaseBracket],
                             Type[Adjust]]:
    """
    Verify validity of parameters and based on them return appropriate
    objects for Context.

    Stop is required.  Take profit and adjust if not used set to
    objects that don't do anything.
    """
    adjust: Type[Adjust]

    if tp_multiple and adjust_tuple:
        assert adjust_tuple[1] < tp_multiple, (
            'Take profit multiple must be > adjust trigger multiple. Otherwise'
            ' position would be closed before stop loss can be adjusted.')

    stop = stop_dict.get(mode)
    if not stop:
        raise ValueError(f"Invalid stop loss type: {mode}. "
                         f"Must be 'fixed' or 'trail'")

    if tp_multiple:
        tp = TakeProfit.set_up(tp_multiple)
    else:
        tp = NoTakeProfit

    if adjust_tuple:
        adjusted_stop = stop_dict.get(adjust_tuple[0])
        if not adjusted_stop:
            raise ValueError(f"Invalid adjusted stop loss type: "
                             f"{adjust_tuple[0]}. "
                             f"Must be 'fixed' or 'trail'")
        adjust = Adjust.set_up(adjusted_stop, adjust_tuple[1], adjust_tuple[2])
    else:
        adjust = NoAdjust

    return (stop, tp, adjust)


def always_on(series: pd.Series) -> bool:
    """
    Based on passed position series determine whether system is always
    in the market (closing position always means opening opposite
    position).
    """
    start = min(series.idxmax(), series.idxmin())
    series = series.loc[start:]
    return series[series == 0].count() == 0


def multiply(series: pd.Series, multiplier):
    """
    Floor multiplied price series to the nearest tick.
    """
    if multiplier != 1:
        tick = get_min_tick(series)
        data = series * multiplier
        floor = data // tick
        return floor * tick
    else:
        return series


def stop_loss(df: pd.DataFrame,
              distance: Union[float, pd.Series],
              mode: StopMode = 'trail',
              tp_multiple: float = 0,
              adjust: Optional[Tuple[StopMode, float, float]] = None,
              multiplier: float = 1,
              price_column: str = 'open',
              return_type: int = 1
              ) -> Union[pd.Series, pd.DataFrame]:
    """
    Apply stop loss and optionally take profit to a strategy.

    Convert a series with transactions or positions into a series with
    positions resulting from applying a specified type of stop loss.

    Stop loss can be trailing or fixed and it might be automatically
    adjustable to a different stop after certain gain has been
    achieved.

    Results of pre-stop/pre-take-profit strategy can be given as
    transactions or positions.  Transactions have values (-1 or 1)
    only when new trade to open or close position is required
    (otherwise zero).  Values of positions indicate what position
    should be held at a given point in time.

    Values in transaction series have the following meaning: 1 - long
    transaction -1 - short transaction 0 - no transaction.  Each row
    indicates whether transaction signal has been generated.

    Values in position series have the following meaning: 1 - long
    position, -1 - short position, 0 - no position.  Each row
    indicates whether position should be kept at this time point.
    Change in position indicates transaction signal.

    This function is a user interface for stop-loss applying
    functions, which ultimately will be numba optimized (when numba
    people get their shit together).

    Args:
    -----

    df - input dataframe, must have following collumns: ['high',
    'low'] - high and low prices for the price bar, and either
    ['transaction'] or ['position'] - result of
    pre-stop/pre-take-profit strategy, if it has both ['position']
    takes precedence

    distance - desired distance of stop loss, which may be given as a
    float if distance value is the same at all time points or a
    pd.Series to give different values for every time point

    mode - stop loss type to apply, possible values: 'fixed', 'trail'

    tp_multiple - take profit distance in price points or omitted if
    none

    adjust - whether stop loss should be adjusted based on distance
    from entry price, if so adjustment should be given as 3 tuple
    where:

    [0] stop loss type to adjust to,

    [1] trigger distance - distance from entry price to adjust
    activation given in multiples of unadjusted stop distance,

    [2] adjusted stop distance - distance value to be used by adjusted
    stop given in multiples of unadjusted stop distance.

    return_type - specify what data is returned, see below

    Returns:
    --------

    Position series resulting from applying the stop-loss/take-profit.

    Format depends on the setting of 'return_type' parameter:

    [1] - position only (pd.Series)

    [2] - position and price (pd.DataFrame)

    [else] - original DataFrame with additional columns: 'position'
    (or 'position_sl' when 'position' was in the origianal df) and
    price (pd.DataFrame)
    """

    assert set(df.columns).issuperset(set(['high', 'low'])
                                      ), "df must have columns: 'high', 'low'"
    assert ('position' in df.columns or 'transaction' in df.columns
            ), "df must have either column 'transaction' or 'position'"
    assert price_column in df.columns, \
        f"'{price_column}' indicated as price column, but not in df"
    assert multiplier > 0, 'Multiplier must be greater than zero.'
    assert isinstance(distance, (pd.Series, float, int)), \
        f'distance must be series or number, not {type(distance)}'

    _df = df.copy()
    _df['distance'] = distance * multiplier
    if 'position' in _df.columns:
        _df['transaction'] = pos_trans(df['position'])
    data = _df[['transaction', 'high', 'low',
                'distance', price_column]].to_numpy()
    params = param_factory(mode, tp_multiple, adjust)
    context = Context(*params, always_on=always_on(_df['position']))
    if return_type == 1:
        return pd.Series(_stop_loss(data, context).T[0].astype('int'),
                         index=df.index)
    elif return_type == 2:
        return pd.DataFrame(_stop_loss(data, context),
                            columns=['position', 'price'], index=df.index)
    else:
        return df.join(pd.DataFrame(_stop_loss(data, context),
                                    columns=['position', 'price'],
                                    index=df.index), rsuffix='_sl')