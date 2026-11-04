from dataclasses import dataclass

from volty.inverters.base import GridState


@dataclass(frozen=True, slots=True)
class GridTracker:
    confirmed: GridState | None = None
    pending: GridState | None = None


def advance(tracker: GridTracker, observed: GridState) -> tuple[GridTracker, GridState | None]:
    """Returns the next tracker and the new grid state if a change was just confirmed.

    A change needs two consecutive readings, so one odd reading never alerts anyone.
    UNKNOWN says nothing about the grid: it may only mean the cloud lost the inverter.
    """
    if observed is GridState.UNKNOWN:
        return tracker, None
    if tracker.confirmed is None or observed is tracker.confirmed:
        return GridTracker(confirmed=observed), None
    if tracker.pending is observed:
        return GridTracker(confirmed=observed), observed
    return GridTracker(confirmed=tracker.confirmed, pending=observed), None
