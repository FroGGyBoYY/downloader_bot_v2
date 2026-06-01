import logging

from telegram import Update
from telegram.ext import ContextTypes


logger = logging.getLogger(__name__)


def _short(value: str | None, limit: int = 300) -> str:
    if not value:
        return ""

    value = str(value).replace("\n", "\\n")

    if len(value) <= limit:
        return value

    return value[:limit] + "..."


def _detect_update_type(update: Update) -> str:
    if update.message:
        return "message"

    if update.edited_message:
        return "edited_message"

    if update.callback_query:
        return "callback_query"

    if update.channel_post:
        return "channel_post"

    if update.my_chat_member:
        return "my_chat_member"

    if update.chat_member:
        return "chat_member"

    return "unknown"


async def raw_update_logger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    text = ""

    if update.message:
        text = update.message.text or update.message.caption or ""

    callback_data = ""
    if update.callback_query:
        callback_data = update.callback_query.data or ""

    logger.debug(
        "RAW_UPDATE | type=%s update_id=%s user_id=%s username=%s chat_id=%s chat_type=%s text=%s callback=%s",
        _detect_update_type(update),
        update.update_id,
        user.id if user else None,
        user.username if user else None,
        chat.id if chat else None,
        chat.type if chat else None,
        _short(text),
        _short(callback_data),
    )
