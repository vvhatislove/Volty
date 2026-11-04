from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

CONNECT = "connect"
CANCEL = "cancel"
LANGUAGES = "languages"
DISCONNECT_LIST = "disconnect_list"
RENAME_LIST = "rename_list"


class BatteryAction(StrEnum):
    OPEN = "open"
    REFRESH = "refresh"


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
