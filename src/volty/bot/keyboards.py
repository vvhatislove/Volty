from collections.abc import Iterable, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from aiogram.types import ReplyKeyboardMarkup as ReplyKeyboard
from aiogram.utils.deep_linking import create_deep_link

from volty.bot import callbacks
from volty.bot.callbacks import (
    BatteryAction,
    BatteryCallback,
    BrandCallback,
    DisconnectCallback,
    GroupView,
    GroupViewCallback,
    LanguageCallback,
    LowChargeCallback,
    LowChargeThresholdCallback,
    RegionCallback,
    RenameCallback,
    SummaryAction,
    SummaryCallback,
    ToggleNotificationsCallback,
    UnlinkGroupCallback,
    VoltageScaleCallback,
)
from volty.bot.i18n import LANGUAGE_NAMES, Translator
from volty.inverters import Brand, brand_regions
from volty.storage.models import Account, Inverter

LOW_CHARGE_THRESHOLDS = (10, 20, 30, 40, 50)


def _rows(*buttons: InlineKeyboardButton) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons])


def main_keyboard(t: Translator) -> ReplyKeyboard:
    return ReplyKeyboard(
        keyboard=[
            [KeyboardButton(text=t("menu.battery")), KeyboardButton(text=t("menu.summary"))],
            [KeyboardButton(text=t("menu.notifications")), KeyboardButton(text=t("menu.settings"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def connect_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(InlineKeyboardButton(text=t("connect.button"), callback_data=callbacks.CONNECT))


def cancel_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL))


def brand_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=t(f"brand.{brand}"), callback_data=BrandCallback(brand=brand).pack()
            )
            for brand in Brand
        ),
        InlineKeyboardButton(text=t("common.cancel"), callback_data=callbacks.CANCEL),
    )


def region_keyboard(t: Translator, brand: Brand) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=t(f"region.{brand}.{region}"),
                callback_data=RegionCallback(brand=brand, region=region).pack(),
            )
            for region in brand_regions(brand)
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


def group_view_keyboard(
    t: Translator, inverters: Sequence[Inverter], *, edit: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    for inverter in inverters:
        prefix = f"{inverter.label}: " if len(inverters) > 1 else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{t(key)}",
                    callback_data=GroupViewCallback(
                        inverter_id=inverter.id, view=view, edit=edit
                    ).pack(),
                )
                for key, view in (
                    ("menu.battery", GroupView.BATTERY),
                    ("menu.summary", GroupView.SUMMARY),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_keyboard(t: Translator, inverter: Inverter) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=t("battery.refresh"),
            callback_data=SummaryCallback(
                inverter_id=inverter.id, action=SummaryAction.REFRESH
            ).pack(),
        )
    ]
    if inverter.group_chat_id is not None:
        buttons.append(
            InlineKeyboardButton(
                text=t("summary.to_group"),
                callback_data=SummaryCallback(
                    inverter_id=inverter.id, action=SummaryAction.SEND_TO_GROUP
                ).pack(),
            )
        )
    return _rows(*buttons)


def summary_choice_keyboard(inverters: Iterable[Inverter]) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=inverter.label,
                callback_data=SummaryCallback(
                    inverter_id=inverter.id, action=SummaryAction.OPEN
                ).pack(),
            )
            for inverter in inverters
        )
    )


def low_charge_choice_keyboard(inverters: Iterable[Inverter]) -> InlineKeyboardMarkup:
    return _rows(
        *(
            InlineKeyboardButton(
                text=inverter.label,
                callback_data=LowChargeCallback(inverter_id=inverter.id).pack(),
            )
            for inverter in inverters
        )
    )


def low_charge_keyboard(t: Translator, inverter: Inverter) -> InlineKeyboardMarkup:
    scale_button = InlineKeyboardButton(
        text=t("low_charge.set_scale"),
        callback_data=VoltageScaleCallback(inverter_id=inverter.id).pack(),
    )
    if inverter.battery_scale is None:
        return _rows(scale_button)
    thresholds = [
        InlineKeyboardButton(
            text=f"✅ {percent}%" if percent == inverter.low_charge_percent else f"{percent}%",
            callback_data=LowChargeThresholdCallback(
                inverter_id=inverter.id, percent=percent
            ).pack(),
        )
        for percent in LOW_CHARGE_THRESHOLDS
    ]
    disable = InlineKeyboardButton(
        text=t("low_charge.disable"),
        callback_data=LowChargeThresholdCallback(inverter_id=inverter.id, percent=0).pack(),
    )
    return InlineKeyboardMarkup(inline_keyboard=[thresholds, [disable], [scale_button]])


def settings_keyboard(t: Translator) -> InlineKeyboardMarkup:
    return _rows(
        InlineKeyboardButton(text=t("connect.button"), callback_data=callbacks.CONNECT),
        InlineKeyboardButton(text=t("settings.rename"), callback_data=callbacks.RENAME_LIST),
        InlineKeyboardButton(
            text=t("settings.low_charge"), callback_data=callbacks.LOW_CHARGE_LIST
        ),
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
                    region=t(f"region.{account.brand}.{account.region}"),
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
