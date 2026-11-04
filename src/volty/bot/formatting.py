from datetime import timedelta

from volty.bot.i18n import Translator
from volty.inverters.base import EnergySummary, GridState, InverterState
from volty.monitoring.alerts import ConnectionChange
from volty.storage.models import Inverter

MISSING_VALUE = "—"
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60


def _soc(inverter: Inverter, state: InverterState) -> str:
    scale = inverter.battery_scale
    if scale is not None and state.battery_voltage is not None:
        return str(scale.percent(state.battery_voltage))
    return MISSING_VALUE if state.soc is None else str(state.soc)


def _voltage(state: InverterState) -> str:
    return MISSING_VALUE if state.battery_voltage is None else f"{state.battery_voltage:.1f}"


def _flow(t: Translator, state: InverterState) -> str:
    if state.is_charging:
        return t("flow.charging", power=state.charge_power)
    if state.is_discharging:
        return t("flow.discharging", power=state.discharge_power)
    return t("flow.idle")


def format_duration(t: Translator, duration: timedelta) -> str:
    total_minutes = max(1, round(duration.total_seconds() / SECONDS_PER_MINUTE))
    hours, minutes = divmod(total_minutes, MINUTES_PER_HOUR)
    if hours:
        return t("duration.hours_minutes", hours=hours, minutes=minutes)
    return t("duration.minutes", minutes=minutes)


def battery_text(t: Translator, inverter: Inverter, state: InverterState) -> str:
    lines = [
        t(
            "battery.status",
            name=inverter.label,
            grid=t(f"grid.{state.grid.value}"),
            soc=_soc(inverter, state),
            voltage=_voltage(state),
            flow=_flow(t, state),
        )
    ]
    if state.load_power is not None:
        lines.append(t("battery.load", power=state.load_power))
    if state.pv_power is not None:
        lines.append(t("battery.pv", power=state.pv_power))
    return "\n".join(lines)


def grid_change_text(
    t: Translator,
    inverter: Inverter,
    state: InverterState,
    change: GridState,
    outage_duration: timedelta | None = None,
) -> str:
    if change is GridState.OFF_GRID:
        key = "alert.off_grid"
    elif state.is_charging:
        key = "alert.on_grid_charging"
    else:
        key = "alert.on_grid"
    text = t(key, name=inverter.label, soc=_soc(inverter, state), voltage=_voltage(state))
    if outage_duration is None:
        return text
    return f"{text}\n{t('alert.outage', duration=format_duration(t, outage_duration))}"


def low_charge_text(t: Translator, inverter: Inverter, percent: int, voltage: float) -> str:
    return t(
        "alert.low_charge",
        name=inverter.label,
        percent=percent,
        voltage=f"{voltage:.1f}",
        threshold=inverter.low_charge_percent,
    )


def connection_text(t: Translator, inverter: Inverter, change: ConnectionChange) -> str:
    key = "alert.offline" if change is ConnectionChange.LOST else "alert.online"
    return t(key, name=inverter.label)


def summary_text(
    t: Translator,
    inverter: Inverter,
    energy: EnergySummary,
    outage_count: int,
    outage_duration: timedelta,
) -> str:
    outages = t("summary.no_outages")
    if outage_count:
        outages = t(
            "summary.outages",
            count=outage_count,
            duration=format_duration(t, outage_duration),
        )
    return t(
        "summary.text",
        name=inverter.label,
        produced=f"{energy.produced:.1f}",
        charged=f"{energy.charged:.1f}",
        discharged=f"{energy.discharged:.1f}",
        consumed=f"{energy.consumed:.1f}",
        imported=f"{energy.imported:.1f}",
        exported=f"{energy.exported:.1f}",
        outages=outages,
    )
