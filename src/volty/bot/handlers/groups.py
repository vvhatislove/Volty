import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import LEAVE_TRANSITION, ChatMemberUpdatedFilter, CommandObject, CommandStart
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from volty.bot.i18n import Translator
from volty.storage.models import User
from volty.storage.repository import clear_group, get_user_inverter

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message(CommandStart(deep_link=True))
async def link_group(
    message: Message,
    command: CommandObject,
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Anyone in a group can type this command, so only the inverter's owner may link it.
    args = command.args or ""
    if message.from_user is None or not args.isdecimal():
        return
    owner_id = message.from_user.id
    async with sessions() as session:
        owner = await session.get(User, owner_id)
        inverter = await get_user_inverter(session, owner_id, int(args))
        if owner is None or inverter is None:
            return
        t = Translator(owner.language)
        title = message.chat.title or ""
        try:
            await message.answer(t("group.linked", name=inverter.label))
        except TelegramAPIError as error:
            logger.warning("Could not post to group %s: %s", message.chat.id, type(error).__name__)
            await bot.send_message(owner_id, t("group.cannot_post", title=title))
            return
        inverter.group_chat_id = message.chat.id
        inverter.group_chat_title = title
        await session.commit()


@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def forget_group(
    event: ChatMemberUpdated, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        await clear_group(session, event.chat.id)
        await session.commit()
