from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.config import Settings
from app.db.admin_repo import get_all_admin_ids, is_admin
from app.db.cookie_auth_repo import to_local_display
from app.db.user_reports_repo import create_user_report, list_recent_user_reports
from app.db.users_repo import get_full_name, get_user_language, upsert_user
from app.telegram_ui.user_messages import localized_message
from app.texts.keys import TextKey


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _tail(update: Update) -> str:
    message = update.message

    if not message:
        return ""

    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _cut(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[:limit - 20] + "\n...truncated"


def _language_for_user(settings: Settings, user_id: int | None) -> str | None:
    if not user_id:
        return None

    try:
        return get_user_language(settings, user_id)
    except Exception:
        return None


async def _save_user_report(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    if not update.message or not update.effective_user:
        return

    settings = _settings(context)
    user = update.effective_user
    upsert_user(settings, user)

    report_id = create_user_report(
        settings,
        user_id=user.id,
        username=user.username,
        full_name=get_full_name(user),
        chat_id=update.effective_chat.id if update.effective_chat else None,
        message_id=update.message.message_id,
        report_text=text[:3000],
    )

    message = localized_message(
        TextKey.HELP_SENT,
        language_code=_language_for_user(settings, user.id),
    )
    await update.message.reply_text(message.text, entities=message.entities)

    admin_text = "\n".join([
        f"User report #{report_id}",
        f"User: {user.id} @{user.username or '-'} | {get_full_name(user) or '-'}",
        "",
        text[:2500],
    ])

    for admin_id in sorted(get_all_admin_ids(settings)):
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_text)
        except Exception:
            pass


async def report_problem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    settings = _settings(context)
    user = update.effective_user
    upsert_user(settings, user)

    text = _tail(update)

    if not text and update.message.reply_to_message:
        replied = update.message.reply_to_message
        replied_text = replied.text or replied.caption or ""
        if replied_text:
            text = f"Проблема с сообщением: {replied_text[:1200]}"

    if not text:
        context.user_data["awaiting_problem_report"] = True
        message = localized_message(
            TextKey.HELP_PROMPT,
            language_code=_language_for_user(settings, user.id),
        )
        await update.message.reply_text(
            message.text,
            entities=message.entities,
        )
        return

    await _save_user_report(update=update, context=context, text=text)


async def pending_problem_report_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_problem_report"):
        return

    if not update.message or not update.effective_user:
        return

    text = (update.message.text or update.message.caption or "").strip()

    if not text:
        return

    context.user_data["awaiting_problem_report"] = False
    await _save_user_report(update=update, context=context, text=text)
    raise ApplicationHandlerStop


async def reports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    settings = _settings(context)
    user = update.effective_user

    if not is_admin(settings, user.id if user else None):
        await update.message.reply_text("Эта команда доступна только админу.")
        return

    rows = list_recent_user_reports(settings, limit=20)
    lines = ["User reports"]

    if not rows:
        lines.append("No reports yet.")
    else:
        for row in rows:
            lines.append(
                f"#{row['id']} {to_local_display(row['created_at'], settings.local_tz_hours)} | "
                f"user {row['user_id']} @{row['username'] or '-'} | {row['status']}\n"
                f"{str(row['report_text'])[:500]}"
            )

    await update.message.reply_text(_cut("\n\n".join(lines)))
