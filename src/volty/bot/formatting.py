from volty.bot.i18n import Translator
from volty.inverters.base import GridState, InverterState
from volty.storage.models import Inverter

MISSING_VALUE = "—"


def _soc(state: InverterState) -> str:
    return MISSING_VALUE if state.soc is None else str(state.soc)


def _voltage(state: InverterState) -> str:
    return MISSING_VALUE if state.battery_voltage is None else f"{state.battery_voltage:.1f}"


def _flow(t: Translator, state: InverterState) -> str:
    if state.is_charging:
        return t("flow.charging", power=state.charge_power)
    if state.is_discharging:
        return t("flow.discharging", power=state.discharge_power)
    return t("flow.idle")


def battery_text(t: Translator, inverter: Inverter, state: InverterState) -> str:
    return t(
        "battery.status",
        name=inverter.label,
        grid=t(f"grid.{state.grid.value}"),
        soc=_soc(state),
        voltage=_voltage(state),
        flow=_flow(t, state),
    )


def grid_change_text(
    t: Translator, inverter: Inverter, state: InverterState, change: GridState
) -> str:
    if change is GridState.OFF_GRID:
        key = "alert.off_grid"
    elif state.is_charging:
        key = "alert.on_grid_charging"
    else:
        key = "alert.on_grid"
    return t(key, name=inverter.label, soc=_soc(state), voltage=_voltage(state))
