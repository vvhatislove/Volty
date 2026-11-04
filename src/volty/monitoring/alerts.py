from dataclasses import dataclass
from enum import Enum, auto

# Charge must recover this far above the threshold before the alert can fire again,
# because battery voltage bounces back as soon as the load drops.
REARM_MARGIN_PERCENT = 5


@dataclass(frozen=True, slots=True)
class LowChargeTracker:
    alerted: bool = False
    pending: bool = False


def advance_low_charge(
    tracker: LowChargeTracker, percent: int, threshold: int, charging: bool
) -> tuple[LowChargeTracker, bool]:
    """Returns the next tracker and whether to alert now.

    A short load spike sags the voltage, so an alert needs two consecutive low readings.
    """
    if tracker.alerted:
        recovered = percent >= threshold + REARM_MARGIN_PERCENT
        return LowChargeTracker(alerted=not recovered), False
    if percent >= threshold or charging:
        return LowChargeTracker(), False
    if tracker.pending:
        return LowChargeTracker(alerted=True), True
    return LowChargeTracker(pending=True), False


class ConnectionChange(Enum):
    LOST = auto()
    RESTORED = auto()


@dataclass(frozen=True, slots=True)
class ConnectionTracker:
    offline_readings: int = 0
    alerted: bool = False


def advance_connection(
    tracker: ConnectionTracker, online: bool, readings_before_alert: int
) -> tuple[ConnectionTracker, ConnectionChange | None]:
    """Dongles drop off briefly all the time, so only a lasting loss of contact alerts."""
    if online:
        change = ConnectionChange.RESTORED if tracker.alerted else None
        return ConnectionTracker(), change
    readings = tracker.offline_readings + 1
    if not tracker.alerted and readings >= readings_before_alert:
        return ConnectionTracker(readings, alerted=True), ConnectionChange.LOST
    return ConnectionTracker(readings, tracker.alerted), None
