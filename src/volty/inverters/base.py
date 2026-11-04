from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class GridState(StrEnum):
    ON_GRID = "on_grid"
    OFF_GRID = "off_grid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Credentials:
    login: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BatteryScale:
    full_voltage: float
    empty_voltage: float

    def percent(self, voltage: float) -> int:
        share = (voltage - self.empty_voltage) / (self.full_voltage - self.empty_voltage)
        return round(min(1.0, max(0.0, share)) * 100)


@dataclass(frozen=True, slots=True)
class InverterInfo:
    serial: str
    model: str


@dataclass(frozen=True, slots=True)
class InverterState:
    online: bool
    grid: GridState
    soc: int | None = None
    battery_voltage: float | None = None
    charge_power: int = 0
    discharge_power: int = 0
    load_power: int | None = None
    pv_power: int | None = None

    @property
    def is_charging(self) -> bool:
        return self.charge_power > 0

    @property
    def is_discharging(self) -> bool:
        return self.discharge_power > 0


@dataclass(frozen=True, slots=True)
class EnergySummary:
    produced: float
    charged: float
    discharged: float
    consumed: float
    imported: float
    exported: float


class InverterError(Exception):
    pass


class AuthenticationError(InverterError):
    pass


class InverterUnavailableError(InverterError):
    pass


class InverterClient(Protocol):
    async def list_inverters(self) -> list[InverterInfo]: ...

    async def read_state(self, serial: str) -> InverterState: ...

    async def read_energy(self, serial: str) -> EnergySummary: ...

    async def aclose(self) -> None: ...
