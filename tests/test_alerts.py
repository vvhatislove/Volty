from volty.inverters.base import BatteryScale
from volty.monitoring.alerts import (
    ConnectionChange,
    ConnectionTracker,
    LowChargeTracker,
    advance_connection,
    advance_low_charge,
)

SCALE = BatteryScale(full_voltage=54.0, empty_voltage=46.0)


def test_scale_maps_voltage_to_percent_and_clamps() -> None:
    assert SCALE.percent(54.0) == 100
    assert SCALE.percent(50.0) == 50
    assert SCALE.percent(46.0) == 0
    assert SCALE.percent(57.0) == 100
    assert SCALE.percent(40.0) == 0


def test_low_charge_needs_two_readings_and_fires_once() -> None:
    tracker, fired = advance_low_charge(LowChargeTracker(), 20, 30, charging=False)
    assert not fired
    assert tracker.pending

    tracker, fired = advance_low_charge(tracker, 20, 30, charging=False)
    assert fired
    assert tracker.alerted

    tracker, fired = advance_low_charge(tracker, 15, 30, charging=False)
    assert not fired


def test_single_voltage_sag_does_not_fire() -> None:
    tracker, _ = advance_low_charge(LowChargeTracker(), 20, 30, charging=False)

    tracker, fired = advance_low_charge(tracker, 40, 30, charging=False)

    assert not fired
    assert tracker == LowChargeTracker()


def test_low_charge_rearms_only_after_recovering_past_margin() -> None:
    alerted = LowChargeTracker(alerted=True)

    assert advance_low_charge(alerted, 32, 30, charging=False) == (alerted, False)
    assert advance_low_charge(alerted, 35, 30, charging=False) == (LowChargeTracker(), False)


def test_charging_battery_does_not_fire() -> None:
    assert advance_low_charge(LowChargeTracker(), 20, 30, charging=True) == (
        LowChargeTracker(),
        False,
    )


def test_connection_alerts_after_limit_and_on_return() -> None:
    tracker = ConnectionTracker()
    for _ in range(2):
        tracker, change = advance_connection(tracker, False, 3)
        assert change is None

    tracker, change = advance_connection(tracker, False, 3)
    assert change is ConnectionChange.LOST

    tracker, change = advance_connection(tracker, False, 3)
    assert change is None

    tracker, change = advance_connection(tracker, True, 3)
    assert change is ConnectionChange.RESTORED
    assert tracker == ConnectionTracker()


def test_brief_connection_loss_stays_silent() -> None:
    tracker, _ = advance_connection(ConnectionTracker(), False, 3)

    tracker, change = advance_connection(tracker, True, 3)

    assert change is None
    assert tracker == ConnectionTracker()
