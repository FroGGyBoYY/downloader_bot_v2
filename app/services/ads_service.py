import asyncio
import logging

from telegram import InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.ads_repo import (
    SCHEDULED_AD,
    get_ad_button,
    get_ad_campaign,
    list_active_ad_campaigns,
    list_ad_buttons,
    record_ad_click,
    record_ad_impression,
    record_ad_send_failure,
)
from app.db.users_repo import is_user_subscribed, list_message_target_users
from app.telegram_ui.button_styles import build_styled_url_button


logger = logging.getLogger(__name__)


AD_CLICK_PREFIX = "adclk:"


def _default_ad_style(index: int) -> str:
    return "success" if index == 0 else "primary"


def build_ad_reply_markup(settings: Settings, ad) -> InlineKeyboardMarkup | None:
    buttons = list_ad_buttons(settings, int(ad["id"]))

    if not buttons:
        return None

    keyboard = []

    for index, button in enumerate(buttons):
        button_text = str(button["button_text"] or "").strip()
        button_url = str(button["button_url"] or "").strip()

        if not button_text or not button_url:
            continue

        style_config = str(button["button_style"] or "").strip() or _default_ad_style(index)

        keyboard.append([
            build_styled_url_button(
                text=button_text,
                url=button_url,
                style_config=style_config,
            )
        ])

    if not keyboard:
        return None

    return InlineKeyboardMarkup(keyboard)


def _looks_like_user_blocked_error(error: Exception) -> bool:
    if isinstance(error, Forbidden):
        return True

    text = str(error).lower()

    return any(
        marker in text
        for marker in (
            "bot was blocked",
            "user is deactivated",
            "forbidden",
            "chat not found",
            "bot can't initiate conversation",
        )
    )


async def send_ad_campaign_to_chat(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    ad,
    chat_id: int,
    user_id: int | None,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    ad_id = int(ad["id"])

    try:
        sent = await context.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=int(ad["source_chat_id"]),
            message_id=int(ad["source_message_id"]),
            reply_markup=build_ad_reply_markup(settings, ad),
            read_timeout=settings.send_read_timeout,
            write_timeout=settings.send_write_timeout,
            connect_timeout=settings.send_connect_timeout,
            pool_timeout=settings.send_pool_timeout,
        )

        record_ad_impression(
            settings,
            ad_id=ad_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=getattr(sent, "message_id", None),
        )

        return True

    except TelegramError as e:
        blocked = _looks_like_user_blocked_error(e)
        record_ad_send_failure(
            settings,
            ad_id=ad_id,
            user_id=user_id,
            chat_id=chat_id,
            error_text=str(e),
            blocked=blocked,
        )
        logger.warning(
            "Ad send failed | ad_id=%s user_id=%s chat_id=%s blocked=%s error=%s",
            ad_id,
            user_id,
            chat_id,
            blocked,
            str(e)[:300],
        )
        return False


async def maybe_send_after_download_ad(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
) -> None:
    if not user_id:
        return

    settings: Settings = context.application.bot_data["settings"]

    try:
        if is_user_subscribed(settings, user_id):
            logger.info("Ad skipped for subscribed user | user_id=%s chat_id=%s", user_id, chat_id)
            return

        ads = list_active_ad_campaigns(settings)

        if not ads:
            return

        for ad in ads:
            ad_id = int(ad["id"])

            sent_ok = await send_ad_campaign_to_chat(
                context=context,
                ad=ad,
                chat_id=chat_id,
                user_id=user_id,
            )

            if sent_ok:
                logger.info(
                    "Ad impression sent | ad_id=%s user_id=%s chat_id=%s",
                    ad_id,
                    user_id,
                    chat_id,
                )

    except Exception:
        logger.exception("Ad service failed | user_id=%s chat_id=%s", user_id, chat_id)


async def send_scheduled_ads_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]

    try:
        ads = list_active_ad_campaigns(settings, campaign_type=SCHEDULED_AD)

        if not ads:
            logger.info("Scheduled ads skipped: no active campaigns")
            return

        users = list_message_target_users(settings, include_friends=False)

        if not users:
            logger.info("Scheduled ads skipped: no eligible users")
            return

        sent_count = 0
        failed_count = 0

        for ad in ads:
            for row in users:
                user_id = int(row["user_id"])

                if is_user_subscribed(settings, user_id):
                    continue

                sent_ok = await send_ad_campaign_to_chat(
                    context=context,
                    ad=ad,
                    chat_id=user_id,
                    user_id=user_id,
                )

                if sent_ok:
                    sent_count += 1
                else:
                    failed_count += 1

                await asyncio.sleep(0.05)

        logger.info(
            "Scheduled ads finished | campaigns=%s users=%s sent=%s failed=%s",
            len(ads),
            len(users),
            sent_count,
            failed_count,
        )

    except Exception:
        logger.exception("Scheduled ads job failed")


async def handle_ad_click(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    ad_id: int,
    button_id: int | None = None,
    user_id: int | None,
    chat_id: int | None,
    message_id: int | None,
) -> str | None:
    settings: Settings = context.application.bot_data["settings"]
    ad = get_ad_campaign(settings, ad_id)

    if not ad:
        return None

    button = get_ad_button(settings, ad_id, button_id)

    if not button:
        return None

    record_ad_click(
        settings,
        ad_id=ad_id,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )

    return str(button["button_url"] or "").strip() or None
