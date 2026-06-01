import logging
import traceback

from telegram import Update
from telegram.ext import ContextTypes

from app.db.errors_repo import record_bot_error
from app.db.users_repo import get_user_language
from app.texts.keys import TextKey
from app.texts.renderer import render_text


logger = logging.getLogger(__name__)


def _format_update(update: object) -> str:
    try:
        if isinstance(update, Update):
            return str(update.to_dict())[:3000]

        return str(update)[:3000]
    except Exception:
        return "Could not format update"


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    settings = context.application.bot_data.get("settings")
    formatted_update = _format_update(update)

    logger.error(
        "UNHANDLED_ERROR | update=%s | error=%s",
        formatted_update,
        repr(error),
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )

    try:
        if settings:
            user = update.effective_user if isinstance(update, Update) else None
            chat = update.effective_chat if isinstance(update, Update) else None
            record_bot_error(
                settings,
                error_type=type(error).__name__ if error else None,
                error_text=repr(error),
                traceback_text="".join(traceback.format_exception(type(error), error, error.__traceback__)) if error else None,
                update_type=type(update).__name__ if update is not None else None,
                user_id=user.id if user else None,
                chat_id=chat.id if chat else None,
                update_preview=formatted_update,
            )
    except Exception:
        logger.exception("Could not save unhandled error to DB")

    try:
        if isinstance(update, Update) and update.effective_chat:
            user = update.effective_user
            language_code = None

            if settings and user:
                try:
                    language_code = get_user_language(settings, user.id)
                except Exception:
                    language_code = getattr(user, "language_code", None)

            text, entities = render_text(
                TextKey.ERROR_INTERNAL,
                language_code=language_code,
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                entities=entities,
            )
    except Exception:
        logger.error("Could not send error message to user")
        logger.error(traceback.format_exc())
