import logging

from pydantic import BaseModel, Field

from volty.inverters.base import GridState, InverterInfo, InverterState

logger = logging.getLogger(__name__)

OFF_GRID_STATUSES = frozenset({64, 96, 128, 136, 192})
GRID_CONNECTED_STATUSES = frozenset({0, 1, 2, 4, 8, 12, 16, 17, 20, 32, 40})
# A grid-connected status with almost no grid voltage is contradictory, so it is not trusted.
MIN_GRID_VOLTAGE = 80.0
# The cloud reports these voltages in tenths of a volt.
VOLTAGE_SCALE = 10


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

    def to_state(self) -> InverterState:
        logger.debug(
            "LuxPower runtime: status=%s lost=%s vacr=%s vBat=%s soc=%s",
            self.status,
            self.lost,
            self.grid_voltage,
            self.battery_voltage,
            self.soc,
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
        )

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
