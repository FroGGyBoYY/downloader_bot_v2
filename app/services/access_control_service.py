from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.database import db_connect
from app.db.settings_repo import get_bool_setting, get_setting, set_setting
from app.db.users_repo import get_user_language, is_user_banned
from app.telegram_ui.user_messages import localized_message, warning_message
from app.texts.keys import TextKey


MAINTENANCE_MODE_KEY = "maintenance_mode"
MAINTENANCE_TEXT_KEY = "maintenance_text"


@dataclass(frozen=True)
class AccessCheck:
    allowed: bool
    reason: str | None = None
    message: str | None = None


def _local_tz(settings: Settings) -> timezone:
    return timezone(timedelta(hours=settings.local_tz_hours))


def _today_utc_bounds(settings: Settings) -> tuple[str, str]:
    tz = _local_tz(settings)
    now_local = datetime.now(timezone.utc).astimezone(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


def is_maintenance_active(settings: Settings) -> bool:
    return get_bool_setting(settings, MAINTENANCE_MODE_KEY, False)


def get_maintenance_text(settings: Settings) -> str:
    return (
        get_setting(settings, MAINTENANCE_TEXT_KEY, settings.maintenance_default_text)
        or settings.maintenance_default_text
    )


def set_maintenance(settings: Settings, *, enabled: bool, text: str | None = None) -> None:
    set_setting(settings, MAINTENANCE_MODE_KEY, "1" if enabled else "0")

    if text is not None:
        set_setting(settings, MAINTENANCE_TEXT_KEY, text)


def get_user_download_count_today(settings: Settings, user_id: int) -> int:
    start_utc, end_utc = _today_utc_bounds(settings)
    conn = db_connect(settings)
    row = conn.execute("""
        SELECT COUNT(*) AS c
        FROM download_requests
        WHERE user_id = ?
            AND status = 'sent'
            AND created_at >= ?
            AND created_at < ?
    """, (user_id, start_utc, end_utc)).fetchone()
    conn.close()
    return int(row["c"] or 0)


def check_download_access(settings: Settings, user_id: int | None) -> AccessCheck:
    if not user_id:
        return AccessCheck(True)

    if is_admin(settings, user_id):
        return AccessCheck(True)

    if is_user_banned(settings, user_id):
        return AccessCheck(
            allowed=False,
            reason="banned",
        )

    if is_maintenance_active(settings):
        return AccessCheck(
            allowed=False,
            reason="maintenance",
            message=get_maintenance_text(settings),
        )

    if settings.daily_limit > 0:
        count_today = get_user_download_count_today(settings, user_id)

        if count_today >= settings.daily_limit:
            return AccessCheck(
                allowed=False,
                reason="daily_limit",
            )

    return AccessCheck(True)


def _language_for_user(settings: Settings, user_id: int | None) -> str | None:
    if not user_id:
        return None

    try:
        return get_user_language(settings, user_id)
    except Exception:
        return None


async def send_access_denied_if_needed(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    reply_to_message_id: int | None = None,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    result = check_download_access(settings, user_id)

    if result.allowed:
        return False

    language_code = _language_for_user(settings, user_id)

    if result.reason == "banned":
        user_message = localized_message(TextKey.ACCESS_BANNED, language_code=language_code)
    elif result.reason == "daily_limit":
        user_message = localized_message(
            TextKey.ACCESS_DAILY_LIMIT,
            language_code=language_code,
            daily_limit=settings.daily_limit,
        )
    elif result.reason == "maintenance" and result.message:
        user_message = warning_message(result.message)
    else:
        user_message = localized_message(TextKey.ACCESS_UNAVAILABLE, language_code=language_code)

    await context.bot.send_message(
        chat_id=chat_id,
        text=user_message.text,
        entities=user_message.entities,
        reply_to_message_id=reply_to_message_id,
        disable_web_page_preview=True,
    )
    return True
