from typing import Any, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.texts.renderer import render_text


async def reply_text(
    update: Update,
    key: str,
    *,
    language_code: str | None = None,
    reply_to_message_id: Optional[int] = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    **variables: Any,
) -> None:
    if not update.message:
        return

    text, entities = render_text(
        key,
        language_code=language_code,
        **variables,
    )

    await update.message.reply_text(
        text=text,
        entities=entities,
        reply_to_message_id=reply_to_message_id,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def send_text(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    key: str,
    *,
    language_code: str | None = None,
    reply_to_message_id: Optional[int] = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    **variables: Any,
) -> None:
    text, entities = render_text(
        key,
        language_code=language_code,
        **variables,
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        entities=entities,
        reply_to_message_id=reply_to_message_id,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )