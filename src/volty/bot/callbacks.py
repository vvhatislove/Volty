from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

CONNECT = "connect"
CANCEL = "cancel"
LANGUAGES = "languages"
DISCONNECT_LIST = "disconnect_list"
RENAME_LIST = "rename_list"
LOW_CHARGE_LIST = "low_charge_list"


class BatteryAction(StrEnum):
    OPEN = "open"
    REFRESH = "refresh"


class SummaryAction(StrEnum):
    OPEN = "open"
    REFRESH = "refresh"
    SEND_TO_GROUP = "group"


class SummaryCallback(CallbackData, prefix="summary"):
    inverter_id: int
    action: SummaryAction


class GroupView(StrEnum):
    BATTERY = "battery"
    SUMMARY = "summary"


class GroupViewCallback(CallbackData, prefix="view"):
    inverter_id: int
    view: GroupView
    edit: bool


class LowChargeCallback(CallbackData, prefix="low"):
    inverter_id: int


class LowChargeThresholdCallback(CallbackData, prefix="low_set"):
    inverter_id: int
    percent: int


class VoltageScaleCallback(CallbackData, prefix="scale"):
    inverter_id: int


class BatteryCallback(CallbackData, prefix="battery"):
    inverter_id: int
    action: BatteryAction


class ToggleNotificationsCallback(CallbackData, prefix="notify"):
    inverter_id: int


class UnlinkGroupCallback(CallbackData, prefix="unlink"):
    inverter_id: int


class RenameCallback(CallbackData, prefix="rename"):
    inverter_id: int


class RegionCallback(CallbackData, prefix="region"):
    region: str


class LanguageCallback(CallbackData, prefix="language"):
    language: str


class DisconnectCallback(CallbackData, prefix="disconnect"):
    account_id: int
    confirmed: bool
