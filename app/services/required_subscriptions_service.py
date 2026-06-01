import logging

import httpx
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.required_subscriptions_repo import (
    CHECKABLE_TYPES,
    CLICK_SATISFIED_TYPES,
    get_required_resource,
    get_required_subscriptions_text,
    is_user_resource_satisfied,
    list_required_resources,
    mark_user_resource_satisfied,
    record_required_event,
)
from app.db.users_repo import is_user_subscribed
from app.db.users_repo import get_user_language
from app.telegram_ui.button_styles import build_styled_inline_button, build_styled_url_button
from app.telegram_ui.user_messages import localized_message
from app.texts.keys import TextKey


logger = logging.getLogger(__name__)

InlineKeyboardButton = build_styled_inline_button


REQUIRED_OPEN_PREFIX = "reqopen:"
REQUIRED_CHECK_CALLBACK = "reqcheck"

SUBSCRIBED_STATUSES = {"creator", "administrator", "member"}
_HELPER_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _helper_client(checker_bot_key: str) -> httpx.AsyncClient:
    client = _HELPER_CLIENTS.get(checker_bot_key)

    if client and not client.is_closed:
        return client

    timeout = httpx.Timeout(connect=20, read=30, write=30, pool=20)
    client = httpx.AsyncClient(timeout=timeout)
    _HELPER_CLIENTS[checker_bot_key] = client
    return client


def _is_subscribed(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id and is_user_subscribed(settings, user_id))


def _language_for_user(settings: Settings, user_id: int | None) -> str | None:
    if not user_id:
        return None

    try:
        return get_user_language(settings, user_id)
    except Exception:
        return None


async def _get_chat_member_via_helper(
    *,
    settings: Settings,
    checker_bot_key: str,
    target_chat: str,
    user_id: int,
) -> str:
    token = settings.helper_bot_tokens.get(checker_bot_key)

    if not token:
        raise RuntimeError(f"helper bot token is not configured: {checker_bot_key}")

    client = _helper_client(checker_bot_key)

    try:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/getChatMember",
            data={
                "chat_id": target_chat,
                "user_id": str(user_id),
            },
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"Telegram helper request failed: {type(e).__name__}") from e

    if response.status_code >= 400:
        raise RuntimeError(f"Telegram helper getChatMember HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError("Telegram helper returned invalid JSON") from e

    if not payload.get("ok"):
        description = str(payload.get("description") or "Telegram getChatMember failed")
        raise RuntimeError(description)

    return str((payload.get("result") or {}).get("status") or "").lower()


async def _get_chat_member_status(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    settings: Settings,
    checker_bot_key: str,
    target_chat: str,
    user_id: int,
) -> str:
    if checker_bot_key == "main":
        member = await context.bot.get_chat_member(
            chat_id=target_chat,
            user_id=user_id,
        )
        return str(getattr(member, "status", "")).lower()

    return await _get_chat_member_via_helper(
        settings=settings,
        checker_bot_key=checker_bot_key,
        target_chat=target_chat,
        user_id=user_id,
    )


async def _is_channel_member(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    settings: Settings,
    resource,
    user_id: int,
    chat_id: int | None,
) -> bool:
    resource_id = int(resource["id"])
    target_chat = str(resource["target_chat"] or "").strip()
    checker_bot_key = str(resource["checker_bot_key"] or "main").strip() or "main"

    if not target_chat:
        record_required_event(
            settings,
            resource_id=resource_id,
            event_type="check_error",
            user_id=user_id,
            chat_id=chat_id,
            error_text="target_chat is empty",
        )
        return False

    try:
        status = await _get_chat_member_status(
            context=context,
            settings=settings,
            checker_bot_key=checker_bot_key,
            target_chat=target_chat,
            user_id=user_id,
        )
        subscribed = status in SUBSCRIBED_STATUSES

        record_required_event(
            settings,
            resource_id=resource_id,
            event_type="pass" if subscribed else "fail",
            user_id=user_id,
            chat_id=chat_id,
        )

        if subscribed:
            mark_user_resource_satisfied(
                settings,
                resource_id=resource_id,
                user_id=user_id,
                satisfied_by=f"telegram_member:{checker_bot_key}",
            )

        return subscribed

    except (BadRequest, Forbidden, TelegramError, httpx.HTTPError, RuntimeError) as e:
        record_required_event(
            settings,
            resource_id=resource_id,
            event_type="check_error",
            user_id=user_id,
            chat_id=chat_id,
            error_text=str(e),
        )
        logger.warning(
            "Required channel check failed | resource_id=%s target=%s checker=%s user_id=%s error=%s",
            resource_id,
            target_chat,
            checker_bot_key,
            user_id,
            str(e)[:300],
        )
        return False


async def get_missing_required_resources(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int | None,
    chat_id: int | None = None,
) -> list:
    if not user_id:
        return []

    settings: Settings = context.application.bot_data["settings"]

    if _is_subscribed(settings, user_id):
        return []

    missing = []

    for resource in list_required_resources(settings, active_only=True):
        resource_type = str(resource["resource_type"] or "").lower()
        resource_id = int(resource["id"])

        if resource_type in CHECKABLE_TYPES:
            if await _is_channel_member(
                context=context,
                settings=settings,
                resource=resource,
                user_id=user_id,
                chat_id=chat_id,
            ):
                continue

            missing.append(resource)
            continue

        if resource_type in CLICK_SATISFIED_TYPES:
            if is_user_resource_satisfied(
                settings,
                resource_id=resource_id,
                user_id=user_id,
            ):
                continue

            missing.append(resource)
            continue

        missing.append(resource)

    return missing


def build_required_subscriptions_keyboard(resources: list) -> InlineKeyboardMarkup:
    keyboard = []

    for resource in resources:
        style_config = str(resource["button_style"] or "").strip() or "primary"
        resource_type = str(resource["resource_type"] or "").lower()
        button_text = str(resource["button_text"] or "Открыть")[:64]
        button_url = str(resource["button_url"] or "").strip()

        if resource_type in CHECKABLE_TYPES and button_url:
            keyboard.append([
                build_styled_url_button(
                    button_text,
                    url=button_url,
                    style_config=style_config,
                )
            ])
            continue

        keyboard.append([
            build_styled_inline_button(
                button_text,
                callback_data=f"{REQUIRED_OPEN_PREFIX}{int(resource['id'])}",
                style_config=style_config,
            )
        ])

    keyboard.append([
        InlineKeyboardButton("Проверить подписку", callback_data=REQUIRED_CHECK_CALLBACK)
    ])

    return InlineKeyboardMarkup(keyboard)


async def record_required_impressions(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    resources: list,
    user_id: int | None,
    chat_id: int | None,
) -> None:
    settings: Settings = context.application.bot_data["settings"]

    for resource in resources:
        record_required_event(
            settings,
            resource_id=int(resource["id"]),
            event_type="impression",
            user_id=user_id,
            chat_id=chat_id,
        )


async def send_required_subscriptions_if_needed(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    reply_to_message_id: int | None = None,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    missing = await get_missing_required_resources(
        context=context,
        user_id=user_id,
        chat_id=chat_id,
    )

    if not missing:
        return False

    await record_required_impressions(
        context=context,
        resources=missing,
        user_id=user_id,
        chat_id=chat_id,
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=get_required_subscriptions_text(settings, _language_for_user(settings, user_id)),
        reply_markup=build_required_subscriptions_keyboard(missing),
        reply_to_message_id=reply_to_message_id,
        disable_web_page_preview=True,
    )

    return True


async def refresh_required_subscriptions_message(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    message_id: int,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    missing = await get_missing_required_resources(
        context=context,
        user_id=user_id,
        chat_id=chat_id,
    )

    if not missing:
        message = localized_message(
            TextKey.REQUIRED_DONE,
            language_code=_language_for_user(settings, user_id),
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message.text,
                entities=message.entities,
                disable_web_page_preview=True,
            )
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise

        return True

    await record_required_impressions(
        context=context,
        resources=missing,
        user_id=user_id,
        chat_id=chat_id,
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=get_required_subscriptions_text(settings, _language_for_user(settings, user_id)),
            reply_markup=build_required_subscriptions_keyboard(missing),
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    return False


async def open_required_resource(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    resource_id: int,
    user_id: int | None,
    chat_id: int | None,
) -> str | None:
    settings: Settings = context.application.bot_data["settings"]
    resource = get_required_resource(settings, resource_id)

    if not resource:
        return None

    record_required_event(
        settings,
        resource_id=resource_id,
        event_type="click",
        user_id=user_id,
        chat_id=chat_id,
    )

    resource_type = str(resource["resource_type"] or "").lower()

    if user_id and resource_type in CLICK_SATISFIED_TYPES:
        mark_user_resource_satisfied(
            settings,
            resource_id=resource_id,
            user_id=user_id,
            satisfied_by="click",
        )

    return str(resource["button_url"] or "").strip() or None
