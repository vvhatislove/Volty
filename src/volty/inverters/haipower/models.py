import logging

from pydantic import BaseModel, Field

from volty.inverters.base import EnergySummary, GridState, InverterInfo, InverterState

logger = logging.getLogger(__name__)

OFF_GRID_STATUS = "OffGrid"
OFFLINE_STATUS = "OffLine"
GRID_PRESENT_STATUSES = frozenset({"OnGrid", "ByPass"})
KNOWN_STATUSES = GRID_PRESENT_STATUSES | {
    OFF_GRID_STATUS,
    OFFLINE_STATUS,
    "Wait",
    "Fault",
    "Flash",
    "SelfCharge",
}
# A status that contradicts the measured grid voltage is not trusted.
MIN_GRID_VOLTAGE = 80.0
# The cloud reports these powers in kilowatts.
WATTS_PER_KILOWATT = 1000
DEFAULT_MODEL = "HaiPower"


class Device(BaseModel):
    serial: str | None = Field(default=None, alias="dsn")
    type_name: str | None = Field(default=None, alias="typeName")


class DeviceListPayload(BaseModel):
    total: int = 0
    rows: list[Device] = []

    def inverters(self) -> list[InverterInfo]:
        return [
            InverterInfo(serial=device.serial, model=device.type_name or DEFAULT_MODEL)
            for device in self.rows
            if device.serial
        ]


class StatePayload(BaseModel):
    status: str | None = Field(default=None, alias="status2")
    soc: float | None = None
    battery_voltage: float | None = Field(default=None, alias="vbat")
    grid_voltage: float | None = Field(default=None, alias="vac1")
    charge_power: float | None = Field(default=None, alias="pcharge")
    discharge_power: float | None = Field(default=None, alias="pdischarge")
    pv_power: float | None = Field(default=None, alias="ppvAll")
    load_power: float | None = Field(default=None, alias="plocalLoadtotal")
    eps_power: float | None = Field(default=None, alias="epsPower")
    last_time: str | None = Field(default=None, alias="lastTime")

    def to_state(self, *, stale: bool) -> InverterState:
        logger.debug(
            "HaiPower state: status2=%s stale=%s lastTime=%s vac1=%s vbat=%s soc=%s ppvAll=%s "
            "plocalLoadtotal=%s epsPower=%s pcharge=%s pdischarge=%s",
            self.status,
            stale,
            self.last_time,
            self.grid_voltage,
            self.battery_voltage,
            self.soc,
            self.pv_power,
            self.load_power,
            self.eps_power,
            self.charge_power,
            self.discharge_power,
        )
        if stale or self.status == OFFLINE_STATUS:
            # The cloud keeps the last readings of an offline inverter, and they are outdated.
            return InverterState(online=False, grid=GridState.UNKNOWN)
        return InverterState(
            online=True,
            grid=self._grid_state(),
            soc=None if self.soc is None else round(self.soc),
            battery_voltage=self.battery_voltage,
            charge_power=_watts(self.charge_power),
            discharge_power=_watts(self.discharge_power),
            load_power=_watts(self.load_power or self.eps_power),
            pv_power=_watts(self.pv_power),
        )

    def _grid_state(self) -> GridState:
        has_grid_voltage = self.grid_voltage is not None and self.grid_voltage >= MIN_GRID_VOLTAGE
        if self.status == OFF_GRID_STATUS:
            # A battery-priority mode runs off-grid while the grid is still there.
            return GridState.UNKNOWN if has_grid_voltage else GridState.OFF_GRID
        if self.status in GRID_PRESENT_STATUSES:
            return GridState.ON_GRID if has_grid_voltage else GridState.UNKNOWN
        if self.status not in KNOWN_STATUSES:
            logger.warning("Unmapped HaiPower status: %s", self.status)
        return GridState.UNKNOWN


class EnergyPayload(BaseModel):
    produced: float | None = Field(default=None, alias="epVAllToday")
    charged: float | None = Field(default=None, alias="echargeToday")
    discharged: float | None = Field(default=None, alias="edischargeToday")
    consumed: float | None = Field(default=None, alias="eloadToday")
    imported: float | None = Field(default=None, alias="efromGridToday")
    exported: float | None = Field(default=None, alias="etoGridToday")

    def to_summary(self) -> EnergySummary:
        logger.debug(
            "HaiPower energy: pv=%s charge=%s discharge=%s load=%s import=%s export=%s",
            self.produced,
            self.charged,
            self.discharged,
            self.consumed,
            self.imported,
            self.exported,
        )
        return EnergySummary(
            produced=self.produced or 0.0,
            charged=self.charged or 0.0,
            discharged=self.discharged or 0.0,
            consumed=self.consumed or 0.0,
            imported=self.imported or 0.0,
            exported=self.exported or 0.0,
        )


def _watts(kilowatts: float | None) -> int:
    return round((kilowatts or 0.0) * WATTS_PER_KILOWATT)
