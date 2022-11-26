import pandas as pd  # type: ignore
import numpy as np
from typing import Optional, Union, Literal, Tuple, Type, TypeVar, Dict, Any
from abc import ABC, abstractmethod

from signal_converters import pos_trans
from vector_backtester import get_min_tick

# ## Stop loss ###

StopMode = Literal["fixed", "trail"]


class BaseBracket(ABC):
    def __init__(self, distance: float, transaction: int, entry: float = 0) -> None:
        self.distance = distance
        self.position = transaction
        self.entry = entry
        self.trigger = self.set_trigger()
        # print(f"bracket init: {self}, e: {entry}")

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
        return (
            f"{self.__class__.__name__}"
            + "("
            + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])
            + ")"
        )


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
                f"Evaluating TrailStop for zero position. " f"Position: {self.position}"
            )


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


stop_dict: Dict[StopMode, Type[BaseBracket]] = {"fixed": FixedStop, "trail": TrailStop}

A = TypeVar("A", bound="Adjust")


class Adjust:

    adjusted_stop: Type[BaseBracket]
    trigger_multiple: float
    stop_multiple: float

    def __init__(
        self, stop_distance: float, transaction: int, entry: float = 0
    ) -> None:
        self.entry = entry
        self.adjusted_stop_distance = stop_distance * self.stop_multiple
        self.adjusted_trigger_distance = stop_distance * self.trigger_multiple
        self.position = transaction
        self.set_trigger()
        self.done = False
        # print(f'Adjust init: {self}')

    @classmethod
    def set_up(
        cls: Type[A],
        adjusted_stop: Type[BaseBracket],
        trigger_multiple: float,
        stop_multiple: float,
    ) -> Type[A]:
        cls.adjusted_stop = adjusted_stop
        cls.trigger_multiple = trigger_multiple
        cls.stop_multiple = stop_multiple
        return cls

    def evaluate(self, order: BaseBracket, high: float, low: float) -> BaseBracket:
        """
        Verify whether stop should be adjusted, return correct stop
        (adjusted or not).

        """
        if self.done:
            return order
        elif (self.position == -1 and self.trigger >= low) or (
            self.position == 1 and self.trigger <= high
        ):

            adjusted = self.adjusted_stop(
                self.adjusted_stop_distance, order.position, entry=self.trigger
            )
            # print(f'Adjusted: {order} to {adjusted} at h: {high}, l: {low}')
            self.done = True
            return adjusted
        else:
            return order

    def set_trigger(self) -> None:
        self.trigger = self.entry + self.adjusted_trigger_distance * self.position

    def __repr__(self):
        return (
            f"{self.__class__.__name__}"
            + "("
            + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])
            + ")"
        )


class NoAdjust(Adjust):
    def __init__(self, *args):
        pass

    def evaluate(self, order: BaseBracket, *args) -> BaseBracket:
        return order


class Context:
    def __init__(
        self,
        stop: Type[BaseBracket],
        tp: Type[BaseBracket],
        adjust: Type[Adjust],
    ) -> None:

        self._stop = stop
        self._tp = tp
        self._adjust = adjust
        self.position = 0
        # print(f'Context init: {self}')

    def __call__(self, row: np.ndarray) -> Tuple[int, float, float, float]:
        (
            self.target_position,  # required position before sl applied
            self.transaction,
            self.high,
            self.low,
            self.distance,
            self.price,
        ) = row
        return self.dispatch()

    def dispatch(self) -> Tuple[int, float, float, float]:
        self.open_price: float = 0
        self.close_price: float = 0
        self.stop_price: float = 0
        if self.position:
            self.eval_for_close()
        else:
            self.eval_for_open()
        return (
            self.position,
            self.open_price,
            self.close_price,
            self.stop_price,
        )

    def eval_for_close(self) -> None:
        if self.transaction == -self.position:
            # print(
            #    f'Close transaction: {self.transaction}, h: {self.high} l: {self.low}')
            # self.close_price = 1  # self.price * -self.position
            self.close_position()
            # this opens oposite position for 'always-on' systems
            self.eval_for_open()
        else:
            self.eval_brackets()

    def eval_for_open(self) -> None:
        if self.transaction and (self.transaction == self.target_position):
            # self.open_price = 1  # self.price * self.transaction
            self.open_position(self.transaction)

    def open_position(self, transaction: int) -> None:
        self.stop = self._stop(self.distance, transaction, self.price)
        self.tp = self._tp(self.distance, transaction, self.price)
        self.adjust = self._adjust(self.distance, transaction, self.price)
        # self.position = self.target_position
        self.open_price = self.price * transaction
        self.position = transaction
        # position may be closed on the same bar, where it's opened
        self.eval_brackets()

    def close_position(self) -> None:
        self.close_price = self.price * -self.position
        self.position = 0
        # print("---------------------")

    def eval_brackets(self) -> None:
        if p := self.stop.evaluate(self.high, self.low):
            # print(f"stop hit: {self.stop}, h: {self.high}, l: {self.low}")
            self.stop_price = p * -self.position
            self.position = 0
        elif p := self.tp.evaluate(self.high, self.low):
            # print(f"tp hit: {self.tp}, h: {self.high}, l: {self.low}")
            self.stop_price = p * -self.position
            self.position = 0
        else:
            self.eval_adjust()

    def eval_adjust(self) -> None:
        self.stop = self.adjust.evaluate(self.stop, self.high, self.low)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}"
            + "("
            + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])
            + ")"
        )


class BlipContext(Context):
    def __call__(self, row: np.ndarray) -> Tuple[int, float, float, float]:
        (
            self.blip,
            self.close_blip,
            self.high,
            self.low,
            self.distance,
            self.price,
        ) = row
        return self.dispatch()

    def eval_for_close(self) -> None:
        if self.close_blip == -self.position:
            self.close_position()
        else:
            self.eval_brackets()

    def eval_for_open(self) -> None:
        if self.blip:
            self.open_position(self.blip)


def _stop_loss(data: np.ndarray, stop: Context) -> np.ndarray:
    """
    Args:
    -----

    data: collumns have the meaning required by the context is being passed.

    Currently
    Context requires:
    [0] position (before the bar is processed, ie. target_position)
    [1] transaction
    [2] high
    [3] low
    [4] distance (required stop distance at given bar)
    [5] price (at which non-stopped transaction will be executed on this bar)

    BlipContext requires:
    [0] blip
    [1] close_blip
    [2] high
    [3] low
    [4] distance (required stop distance at given bar)
    [5] price (at which non-stopped transaction will be executed on this bar)

    """

    position = np.zeros((data.shape[0], 1), dtype=np.int8)
    open_price = np.zeros((data.shape[0], 1), dtype=np.float32)
    close_price = np.zeros((data.shape[0], 1), dtype=np.float32)
    stop_price = np.zeros((data.shape[0], 1), dtype=np.float32)
    for i, row in enumerate(data):
        position[i], open_price[i], close_price[i], stop_price[i] = stop(row)
    return np.concatenate((position, open_price, close_price, stop_price), axis=1)


def param_factory(
    mode: StopMode,
    tp_multiple: Optional[float] = None,
    adjust_tuple: Optional[Tuple[StopMode, float, float]] = None,
) -> Tuple[Type[BaseBracket], Type[BaseBracket], Type[Adjust]]:
    """
    Verify validity of parameters and based on them return appropriate
    objects for Context.

    Stop is required.  Take profit and adjust if not used set to
    objects that don't do anything.
    """
    adjust: Type[Adjust]

    if tp_multiple and adjust_tuple:
        assert adjust_tuple[1] < tp_multiple, (
            "Take profit multiple must be > adjust trigger multiple. Otherwise"
            " position would be closed before stop loss can be adjusted."
        )

    stop = stop_dict.get(mode)
    if not stop:
        raise ValueError(f"Invalid stop loss type: {mode}. Must be 'fixed' or 'trail'")

    if tp_multiple:
        tp = TakeProfit.set_up(tp_multiple)
    else:
        tp = NoTakeProfit

    if adjust_tuple:
        adjusted_stop = stop_dict.get(adjust_tuple[0])
        if not adjusted_stop:
            raise ValueError(
                f"Invalid adjusted stop loss type: {adjust_tuple[0]}. "
                f"Must be 'fixed' or 'trail'"
            )
        adjust = Adjust.set_up(adjusted_stop, adjust_tuple[1], adjust_tuple[2])
    else:
        adjust = NoAdjust

    return (stop, tp, adjust)


def always_on(series: pd.Series) -> bool:
    """
    NOT IN USE
    Based on passed position series determine whether system is always
    in the market (closing position always means opening opposite
    position).
    """
    start = min(series.idxmax(), series.idxmin())
    series = series.loc[start:]  # type: ignore
    return series[series == 0].count() == 0


def round_tick(series: pd.Series) -> pd.Series:
    tick = get_min_tick(series)
    floor = series // tick
    remainder = series % tick
    return floor * tick + 1 * (remainder > tick / 2)


def multiply(series: pd.Series, multiplier: float) -> pd.Series:
    """
    Floor multiplied price series to the nearest tick.
    """
    if multiplier != 1:
        series = series * multiplier
    return round_tick(series)


def stop_loss(
    df: pd.DataFrame,
    distance: Union[float, pd.Series],
    mode: StopMode = "trail",
    tp_multiple: float = 0,
    adjust: Optional[Tuple[StopMode, float, float]] = None,
    multiplier: float = 1,
    price_column: str = "open",
    **kwargs,
) -> pd.DataFrame:
    """Apply stop loss and optionally take profit to a strategy.

    Convert a series with transactions or positions into a series with
    positions resulting from applying a specified type of stop loss.

    Stop loss can be trailing or fixed and it might be automatically
    adjustable to a different stop after certain gain has been
    achieved.

    Results of pre-stop/pre-take-profit strategy can be given as
    positions or blips.

    This function is a user interface for stop-loss applying
    functions, which ultimately will be numba optimized (when numba
    people get their shit together).

    Args:
    -----

    df - input dataframe, must have following collumns: ['high',
    'low'] - high and low prices for the price bar, and either
    ['position'] or ['blip']- result of pre-stop/pre-take-profit
    strategy, if it has both ['position'] takes precedence. If blip is
    given, additionally, close blip can also be provided, then blip is
    to open positions close_blip to close. If only blip given, it will
    be used to both open and close positions.  Blips must be shifted
    to appear at the appropriate point in time, i.e. they must appear
    at the time points where transaction should be executed (similarly
    position changes at the points in time where transaction should be
    executed). Stop will not shift blilps (or any other indicators).

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

    [2] - open, close, stop price and position (pd.DataFrame)

    [else] - original DataFrame merged with results of the stop loss
    """

    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    if not set(df.columns).issuperset(set(["high", "low"])):
        raise ValueError("df must have columns: 'high', 'low'")
    if not ("position" in df.columns or "blip" in df.columns):
        raise ValueError("df must have either column 'position'or 'blip'")
    if not (price_column in df.columns):
        raise ValueError(f"'{price_column}' indicated as price column, but not in df")
    if multiplier <= 0:
        raise ValueError("Multiplier must be greater than zero.")
    if not isinstance(distance, (pd.Series, float, int)):
        raise ValueError(f"distance must be series or number, not {type(distance)}")

    _df = df.copy()
    _df["distance"] = distance * multiplier

    params = param_factory(mode, tp_multiple, adjust)

    if "position" in _df.columns:
        _df["transaction"] = pos_trans(df["position"])
        _df["position"] = _df["position"].astype(int, copy=False)
        data_fields = [
            "position",
            "transaction",
            "high",
            "low",
            "distance",
            price_column,
        ]
        context = Context(*params)
    else:
        if "close_blip" not in _df.columns:
            _df["close_blip"] = _df["blip"]
        # we want to be returning positions rather than signals
        # blips have to be shifted (before upsampling)
        _df["blip"] = _df["blip"]
        _df["close_blip"] = _df["close_blip"]
        data_fields = [
            "blip",
            "close_blip",
            "high",
            "low",
            "distance",
            price_column,
        ]
        context = BlipContext(*params)

    data = _df[[*data_fields]].to_numpy()
    result = _stop_loss(data, context)

    out_df = pd.DataFrame(
        result,
        columns=["position", "open_price", "close_price", "stop_price"],
        index=df.index,
    )
    out_df["position"] = out_df["position"].astype(int, copy=False)
    return out_df
