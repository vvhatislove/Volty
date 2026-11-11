import pytest

from volty.bot.formatting import battery_text
from volty.bot.i18n import Translator
from volty.inverters.base import GridState, InverterState
from volty.storage.models import Inverter

INVERTER = Inverter(serial="0000000001", model="LXP")


def screen(grid: GridState, grid_voltage: float | None, output_voltage: float | None) -> str:
    state = InverterState(
        online=True,
        grid=grid,
        soc=71,
        battery_voltage=53.0,
        grid_voltage=grid_voltage,
        output_voltage=output_voltage,
    )
    return battery_text(Translator("en"), INVERTER, state)


def test_grid_voltage_is_shown_while_the_power_is_on() -> None:
    text = screen(GridState.ON_GRID, 206.4, 206.6)

    assert "Grid: power is on · 206 V" in text
    assert "Inverter output" not in text


@pytest.mark.parametrize(
    ("grid", "grid_voltage", "output_voltage", "shown"),
    [
        (GridState.ON_GRID, 206.0, 230.0, "230 V"),
        (GridState.OFF_GRID, None, 229.6, "230 V"),
        (GridState.UNKNOWN, 0.0, 228.0, "228 V"),
    ],
    ids=["differs from the grid", "power is out", "grid is unknown"],
)
def test_inverter_output_is_shown_when_it_is_not_the_grid(
    grid: GridState, grid_voltage: float | None, output_voltage: float, shown: str
) -> None:
    text = screen(grid, grid_voltage, output_voltage)

    assert f"Inverter output: {shown}" in text


def test_missing_voltages_leave_the_screen_as_before() -> None:
    text = screen(GridState.OFF_GRID, None, None)

    assert "Grid: no power, running on batteries\nCharge: 71%" in text
