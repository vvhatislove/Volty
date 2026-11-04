from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.types import ReplyKeyboardMarkup as ReplyKeyboard
from aiogram.utils.deep_linking import create_deep_link

from volty.bot import callbacks
from volty.bot.callbacks import (
    BatteryAction,
    BatteryCallback,
    DisconnectCallback,
    LanguageCallback,
    RegionCallback,
    RenameCallback,
    ToggleNotificationsCallback,
    UnlinkGroupCallback,
)
from volty.bot.i18n import LANGUAGE_NAMES, Translator
from volty.storage.models import Account, Inverter


def _rows(*buttons: InlineKeyboardButton) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons])


def main_keyboard(t: Translator) -> ReplyKeyboard:
    return ReplyKeyboard(
        keyboard=[
            [KeyboardButton(text=t("menu.battery")), KeyboardButton(text=t("menu.notifications"))],
            [KeyboardButton(text=t("menu.settings"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def connect_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(InlineKeyboardButton(text=t("connect.button"), callback_data=callbacks.CONNECT))


def cancel_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL))


def region_keyboard(t: Translator, regions: Iterable[str]) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=t(f"region.{region}"), callback_data=RegionCallback(region=region).pack()
            )
            for region in regions
        ),
        InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL),
    )


def _battery_button(text: str, inverter_id: int, action: BatteryAction) -> InlineKeyboardButton:
    data = BatteryCallback(inverter_id=inverter_id, action=action)
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def battery_shortcut_keyboard(t: Translator, inverter_id: int) -> InlineKeyboardMarkup:
    return _rows(_battery_button(t("menu.battery"), inverter_id, BatteryAction.OPEN))


def battery_refresh_keyboard(t: Translator, inverter_id: int) -> InlineKeyboardMarkup:
    return _rows(_battery_button(t("battery.refresh"), inverter_id, BatteryAction.REFRESH))


def battery_choice_keyboard(inverters: Iterable[Inverter]) -> InlineKeyboardMarkup:
    return _rows(
        *(_battery_button(i.label, i.id, BatteryAction.OPEN) for i in inverters),
    )


def _group_button(t: Translator, inverter: Inverter, bot_username: str) -> InlineKeyboardButton:
    if inverter.group_chat_id is None:
        return InlineKeyboardButton(
            text=t("group.add", name=inverter.label),
            url=create_deep_link(bot_username, "startgroup", str(inverter.id)),
        )
    return InlineKeyboardButton(
        text=t("group.remove", name=inverter.label, title=inverter.group_chat_title),
        callback_data=UnlinkGroupCallback(inverter_id=inverter.id).pack(),
    )


def notifications_keyboard(
    t: Translator, inverters: Iterable[Inverter], bot_username: str
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for inverter in inverters:
        key = "notifications.on" if inverter.notifications_enabled else "notifications.off"
        buttons.append(
            InlineKeyboardButton(
                text=t(key, name=inverter.label),
                callback_data=ToggleNotificationsCallback(inverter_id=inverter.id).pack(),
            )
        )
        buttons.append(_group_button(t, inverter, bot_username))
    return _rows(*buttons)


def rename_choice_keyboard(t: Translator, inverters: Iterable[Inverter]) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=inverter.label,
                callback_data=RenameCallback(inverter_id=inverter.id).pack(),
            )
            for inverter in inverters
        ),
        InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL),
    )


def settings_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(
        InlineKeyboardButton(text=t("connect.button"), callback_data=callbacks.CONNECT),
        InlineKeyboardButton(text=t("settings.rename"), callback_data=callbacks.RENAME_LIST),
        InlineKeyboardButton(text=t("settings.language"), callback_data=callbacks.LANGUAGES),
        InlineKeyboardButton(
            text=t("settings.disconnect"), callback_data=callbacks.DISCONNECT_LIST
        ),
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=name, callback_data=LanguageCallback(language=language).pack()
            )
            for language, name in LANGUAGE_NAMES.items()
        )
    )


def disconnect_list_keyboard(t: Translator, accounts: Iterable[Account]) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=t(
                    "disconnect.account",
                    region=t(f"region.{account.region}"),
                    count=len(account.inverters),
                ),
                callback_data=DisconnectCallback(account_id=account.id, confirmed=False).pack(),
            )
            for account in accounts
        ),
        InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL),
    )


def disconnect_confirm_keyboard(t: Translator, account_id: int) -> InlineKeyboardMarkup:
    return _rows(
        InlineKeyboardButton(
            text=t("disconnect.yes"),
            callback_data=DisconnectCallback(account_id=account_id, confirmed=True).pack(),
        ),
        InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL),
    )
