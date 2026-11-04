import logging

from pydantic import BaseModel, Field

from volty.inverters.base import EnergySummary, GridState, InverterInfo, InverterState

logger = logging.getLogger(__name__)

OFF_GRID_STATUSES = frozenset({64, 96, 128, 136, 192})
GRID_CONNECTED_STATUSES = frozenset({0, 1, 2, 4, 8, 12, 16, 17, 20, 32, 40})
# A grid-connected status with almost no grid voltage is contradictory, so it is not trusted.
MIN_GRID_VOLTAGE = 80.0
# The cloud reports these voltages in tenths of a volt.
VOLTAGE_SCALE = 10
# The cloud reports energy in tenths of a kilowatt-hour.
ENERGY_SCALE = 10


class LoginInverter(BaseModel):
    serial_num: str = Field(alias="serialNum")
    device_type_text: str = Field(default="LuxPower", alias="deviceTypeText")


class LoginPlant(BaseModel):
    inverters: list[LoginInverter] = []


class LoginPayload(BaseModel):
    plants: list[LoginPlant] = []

    def inverters(self) -> list[InverterInfo]:
        return [
            InverterInfo(serial=inverter.serial_num, model=inverter.device_type_text)
            for plant in self.plants
            for inverter in plant.inverters
        ]


class RuntimePayload(BaseModel):
    lost: bool = False
    status: int | None = None
    soc: int | None = None
    battery_voltage: int | None = Field(default=None, alias="vBat")
    grid_voltage: int | None = Field(default=None, alias="vacr")
    charge_power: int | None = Field(default=None, alias="pCharge")
    discharge_power: int | None = Field(default=None, alias="pDisCharge")
    pv_power: int | None = Field(default=None, alias="ppv")
    eps_power: int | None = Field(default=None, alias="peps")
    consumption_power: int | None = Field(default=None, alias="consumptionPower")
    grid_import_power: int | None = Field(default=None, alias="pToUser")
    grid_export_power: int | None = Field(default=None, alias="pToGrid")

    def to_state(self) -> InverterState:
        logger.debug(
            "LuxPower runtime: status=%s lost=%s vacr=%s vBat=%s soc=%s ppv=%s peps=%s "
            "consumption=%s pToUser=%s pToGrid=%s pCharge=%s pDisCharge=%s",
            self.status,
            self.lost,
            self.grid_voltage,
            self.battery_voltage,
            self.soc,
            self.pv_power,
            self.eps_power,
            self.consumption_power,
            self.grid_import_power,
            self.grid_export_power,
            self.charge_power,
            self.discharge_power,
        )
        return InverterState(
            online=not self.lost,
            grid=self._grid_state(),
            soc=self.soc,
            battery_voltage=(
                None if self.battery_voltage is None else self.battery_voltage / VOLTAGE_SCALE
            ),
            charge_power=self.charge_power or 0,
            discharge_power=self.discharge_power or 0,
            load_power=None if self.lost else self._load_power(),
            pv_power=None if self.lost else self.pv_power or 0,
        )

    def _load_power(self) -> int:
        # Not every model fills the consumption field, so fall back to the energy balance.
        balance = (
            (self.pv_power or 0)
            + (self.discharge_power or 0)
            - (self.charge_power or 0)
            + (self.grid_import_power or 0)
            - (self.grid_export_power or 0)
        )
        return self.consumption_power or self.eps_power or max(0, balance)

    def _grid_state(self) -> GridState:
        if self.lost or self.status is None:
            return GridState.UNKNOWN
        if self.status in OFF_GRID_STATUSES:
            return GridState.OFF_GRID
        if self.status not in GRID_CONNECTED_STATUSES:
            logger.warning("Unmapped LuxPower status code: %s", self.status)
            return GridState.UNKNOWN
        if self.grid_voltage is None or self.grid_voltage / VOLTAGE_SCALE < MIN_GRID_VOLTAGE:
            return GridState.UNKNOWN
        return GridState.ON_GRID


class EnergyPayload(BaseModel):
    today_yielding: int = Field(alias="todayYielding")
    today_charging: int = Field(alias="todayCharging")
    today_discharging: int = Field(alias="todayDischarging")
    today_usage: int = Field(alias="todayUsage")
    today_import: int = Field(alias="todayImport")
    today_export: int = Field(alias="todayExport")

    def to_summary(self) -> EnergySummary:
        logger.debug(
            "LuxPower energy: yielding=%s charging=%s discharging=%s usage=%s import=%s export=%s",
            self.today_yielding,
            self.today_charging,
            self.today_discharging,
            self.today_usage,
            self.today_import,
            self.today_export,
        )
        return EnergySummary(
            produced=self.today_yielding / ENERGY_SCALE,
            charged=self.today_charging / ENERGY_SCALE,
            discharged=self.today_discharging / ENERGY_SCALE,
            consumed=self.today_usage / ENERGY_SCALE,
            imported=self.today_import / ENERGY_SCALE,
            exported=self.today_export / ENERGY_SCALE,
        )
