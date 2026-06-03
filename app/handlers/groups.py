import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.db.admin_repo import get_all_admin_ids
from app.db.groups_repo import upsert_bot_group
from app.texts.keys import TextKey
from app.texts.renderer import render_text


logger = logging.getLogger(__name__)


ACTIVE_BOT_STATUSES = {"member", "administrator"}


def _status(value) -> str:
    return str(value or "").lower()


async def _notify_admins(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    settings = context.application.bot_data.get("settings")

    if not settings:
        return

    for admin_id in sorted(get_all_admin_ids(settings)):
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text[:3900],
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Could not notify admin about group update | admin_id=%s", admin_id)


async def bot_chat_member_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    event = update.my_chat_member

    if not event:
        return

    chat = event.chat
    old_status = _status(getattr(event.old_chat_member, "status", None))
    new_status = _status(getattr(event.new_chat_member, "status", None))
    chat_type = str(getattr(chat, "type", "") or "")
    chat_title = getattr(chat, "title", None) or str(chat.id)

    logger.info(
        "Bot chat member update | chat_id=%s chat_type=%s title=%s old=%s new=%s",
        chat.id,
        chat_type,
        chat_title,
        old_status,
        new_status,
    )

    was_active = old_status in ACTIVE_BOT_STATUSES
    is_active = new_status in ACTIVE_BOT_STATUSES
    settings = context.application.bot_data.get("settings")
    actor = getattr(event, "from_user", None)
    actor_id = getattr(actor, "id", None)

    if settings and chat_type in {"group", "supergroup"}:
        try:
            upsert_bot_group(
                settings,
                chat,
                status="active" if is_active else (new_status or "removed"),
                added_by_user_id=actor_id if is_active and not was_active else None,
            )
        except Exception:
            logger.exception("Could not save group membership | chat_id=%s", chat.id)

    if is_active and not was_active:
        if chat_type in {"group", "supergroup"}:
            bot_username = context.application.bot_data.get("bot_username")
            mention_hint = f", @{bot_username}" if bot_username else ""
            actor_language = getattr(getattr(event, "from_user", None), "language_code", None)
            text, entities = render_text(
                TextKey.GROUP_WELCOME,
                language_code=actor_language,
                mention_hint=mention_hint,
            )

            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=text,
                    entities=entities,
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Could not send group welcome | chat_id=%s", chat.id)

        await _notify_admins(
            context=context,
            text=(
                "Бота добавили в чат.\n"
                f"Название: {chat_title}\n"
                f"chat_id: {chat.id}\n"
                f"type: {chat_type}\n"
                f"status: {new_status}"
            ),
        )

    elif was_active and not is_active:
        await _notify_admins(
            context=context,
            text=(
                "Бота убрали из чата.\n"
                f"Название: {chat_title}\n"
                f"chat_id: {chat.id}\n"
                f"type: {chat_type}\n"
                f"status: {new_status}"
            ),
        )
