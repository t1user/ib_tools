from __future__ import annotations

import logging
from typing import Any, Literal, Optional, Type

from ib_tools.base import Atom
from ib_tools.manager import STATE_MACHINE
from ib_tools.misc import Action, Signal, sign
from ib_tools.state_machine import StateMachine

log = logging.getLogger(__name__)


class BinarySignalProcessor(Atom):
    """
    Process binary signals, i.e. long/short/off, as opposed to
    descrete signals, where signal strength is meaningful (e.g. signal
    assuming values -10...10 based on strength of conviction).

    Actual position size or even whether the position should be taken
    at all is not determined here, it's the job of `Portfolio`.

    * Zero signal means close position if position exists, ignored
    otherwise

    * Non-zero signal means:

    ** open new position if there is no position for the strategy

    ** ignore signal if it's in the same direction as existing
    position

    ** reverse position if the signal is in the direction opposite to
    existing position

    This behaviour can be modified in sub-classes, by overriding
    methods: :meth:`process_position` and :meth:`process_no_position`.

    Whatever the meaning of the signal coming in, signal coming out
    means strategy wants to take `action` in the direction of
    `signal`, as indicated by keys `action` and `signal` in the
    emitted dict.  Incoming signals that don't require any action will
    be stopped here and not propagated down the chain.
    """

    def __init__(self, state_machine: Optional[StateMachine] = None) -> None:
        super().__init__()
        self.sm = state_machine or STATE_MACHINE
        self.strategy: str = ""
        log.debug(f"Signal processor initialized: {self}")

    # onStart should set strategy

    def onData(self, data: dict[str, Any], *args) -> None:
        try:
            signal = data["signal"]
        except KeyError:
            log.exception(f"Missing signal data {data}")
        strategy = data.get("strategy") or self.strategy
        if result := self.process_signal(strategy, signal):
            data.update(
                {
                    "action": result,
                    "target_position": self.target_position(signal, result),
                    "existing_position": self.position(strategy),
                }
            )
            self.dataEvent.emit(data)

    def target_position(self, signal, result):
        if result == "OPEN":
            return signal
        elif result == "REVERSE":
            return signal
        elif result == "CLOSE":
            return 0
        else:
            log.error(
                f"{self} generated unknown signal: {result} for strategy: "
                f"{self.strategy}"
            )

    def process_signal(self, strategy: str, signal: Signal) -> Optional[Action]:
        if not self.position(strategy):
            return self.process_no_position(strategy, signal)
        elif not self.same_direction(strategy, signal):
            return self.process_position(strategy, signal)
        else:
            return None

    def position(self, strategy: str) -> Signal:
        """
        Which side of the market is position on: (short: -1, long: 1,
        no position: 0)
        """
        return sign(self.sm.position(strategy))

    def same_direction(self, strategy: str, signal: Signal) -> bool:
        """Is signal and position in the same direction?"""
        return self.position(strategy) == signal

    def process_position(self, strategy: str, signal: Signal) -> Optional[Action]:
        if signal == 0:
            return self.process_zero_signal_position(strategy, signal)
        else:
            return self.process_non_zero_signal_position(strategy, signal)

    def process_no_position(self, strategy: str, signal: Signal) -> Optional[Action]:
        if signal == 0:
            return self.process_zero_signal_no_position(strategy, signal)
        else:
            return self.process_non_zero_signal_no_position(strategy, signal)

    def process_zero_signal_position(self, strategy, signal):
        return None

    def process_zero_signal_no_position(self, strategy, signal):
        return None

    def process_non_zero_signal_position(self, strategy, signal):
        # We've already checked signal is not same direction as position
        return "CLOSE"

    def process_non_zero_signal_no_position(self, strategy, signal):
        return "OPEN"

    def __repr__(self):
        return self.__class__.__name__ + "()"


class LockableBinarySignalProcessor(BinarySignalProcessor):
    """
    * Signals in the direction of last position are ignored (one side
    of the market is 'locked').  It's up to :class:`StateMachine` to
    determine which side is 'locked' based on position actually taken
    in the market (not just previously generated signals).

    * Zero signal means close position if position exists, ignored
    otherwise
    """

    def locked(self, strategy: str, signal: Signal) -> bool:
        return self.sm.locked(strategy) == signal

    def process_zero_signal_position(self, strategy, signal):
        return "CLOSE"

    def process_non_zero_signal_position(self, strategy, signal):
        # We've already checked signal is not same direction as position
        # Zero signal means "CLOSE", oppposite signal means "REVERSE"
        return "REVERSE"

    def process_non_zero_signal_no_position(self, strategy, signal):
        if self.locked(strategy, signal):
            return None
        else:
            return "OPEN"


class LockableBlipBinarySignalProcessor(LockableBinarySignalProcessor):
    """
    * Signals in the direction of last position are ignored (one side
    of the market is 'locked').  It's up to :class:`StateMachine` to
    determine which side is 'locked' based on position actually taken
    in the market (not just previously generated signals).

    * Zero signal means close position if position exists, ignored
    otherwise
    """

    def process_zero_signal_position(self, strategy, signal):
        return None

    def process_zero_signal_no_position(self, strategy, signal):
        return None

    def process_non_zero_signal_position(self, strategy, signal):
        # We've already checked signal is not same direction as position
        # Zero signal means "CLOSE", oppposite signal means "REVERSE"
        return "CLOSE"


class AlwaysOnLockableBinarySignalProcessor(LockableBinarySignalProcessor):
    def process_non_zero_signal_position(self, strategy, signal):
        return "REVERSE"


class AlwaysOnBinarySignalProcessor(BinarySignalProcessor):
    def target_position(self, signal, result):
        if result == "OPEN":
            return signal
        elif result == "REVERSE":
            return signal
        elif result == "CLOSE":
            return 0
        else:
            log.error(
                f"{self} generated unknown signal: {result} for strategy: "
                f"{self.strategy}"
            )

    def process_non_zero_signal_position(self, strategy, signal):
        return "REVERSE"


def binary_signal_processor_factory(
    lockable=False, always_on=False
) -> Type[BinarySignalProcessor]:
    if lockable and always_on:
        return AlwaysOnLockableBinarySignalProcessor
    elif lockable:
        return LockableBinarySignalProcessor
    elif always_on:
        return AlwaysOnBinarySignalProcessor
    else:
        return BinarySignalProcessor
