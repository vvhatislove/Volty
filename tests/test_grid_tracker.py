from volty.inverters.base import GridState
from volty.monitoring.grid import GridTracker, advance

ON = GridState.ON_GRID
OFF = GridState.OFF_GRID
UNKNOWN = GridState.UNKNOWN


def test_first_reading_sets_state_silently() -> None:
    assert advance(GridTracker(), OFF) == (GridTracker(confirmed=OFF), None)


def test_change_needs_two_consecutive_readings() -> None:
    tracker, change = advance(GridTracker(confirmed=ON), OFF)
    assert change is None
    assert tracker == GridTracker(confirmed=ON, pending=OFF)

    tracker, change = advance(tracker, OFF)
    assert change is OFF
    assert tracker == GridTracker(confirmed=OFF)


def test_single_odd_reading_is_forgotten() -> None:
    tracker, _ = advance(GridTracker(confirmed=ON), OFF)

    tracker, change = advance(tracker, ON)

    assert change is None
    assert tracker == GridTracker(confirmed=ON)


def test_unknown_changes_nothing() -> None:
    tracker = GridTracker(confirmed=ON, pending=OFF)

    assert advance(tracker, UNKNOWN) == (tracker, None)
    assert advance(GridTracker(), UNKNOWN) == (GridTracker(), None)
