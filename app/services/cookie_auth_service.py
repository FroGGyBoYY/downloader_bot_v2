import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from telegram.ext import ContextTypes

from app.config import Settings
from app.db.cookie_auth_repo import (
    COOKIE_SLOTS,
    CookieRotationRecord,
    get_auth_slot,
    increment_cookie_success,
    normalize_cookie_platform,
    rotate_auth_slot,
)
from app.db.proxy_pool_repo import is_proxy_error
from app.downloader.cookies import (
    detect_cookie_platform,
    get_auth_name,
    get_cookie_slot_path,
    is_cookie_slot_usable,
)


logger = logging.getLogger(__name__)


AUTH_ERROR_MARKERS = (
    "login",
    "log in",
    "sign in",
    "cookie",
    "cookies",
    "captcha",
    "403",
    "401",
    "429",
    "forbidden",
    "unauthorized",
    "too many requests",
    "rate limit",
    "ratelimit",
    "limited access",
    "temporarily limited",
    "google sorry",
    "google.com/sorry",
    "sorry/index",
    "consent.youtube.com",
    "not logged in",
    "authentication",
    "http redirect to login page",
    "no working app info",
    "not available in your country",
)


PLATFORM_LABELS = {
    "youtube": "Ютуб",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "pinterest": "Pinterest",
}


PLATFORM_COMMAND_PREFIXES = {
    "youtube": "ccy",
    "instagram": "cci",
    "tiktok": "cct",
    "pinterest": "ccp",
}


@dataclass(frozen=True)
class CookieAuthResult:
    value: Any
    platform: str | None
    slot: int | None
    auth_name: str | None


def platform_from_url_or_name(value: str | None) -> str | None:
    platform = normalize_cookie_platform(value)

    if platform:
        return platform

    return detect_cookie_platform(value)


def is_auth_related_error(error: BaseException | str | None) -> bool:
    if error is None:
        return False

    if is_proxy_error(error):
        return False

    text = str(error).lower()
    return any(marker in text for marker in AUTH_ERROR_MARKERS)


def _short_reason(error: BaseException | str | None, limit: int = 450) -> str:
    text = str(error or "").replace("\n", " ").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _slot_label(platform: str, slot: int) -> str:
    platform_label = PLATFORM_LABELS.get(platform, platform)

    if slot == 0:
        return "гость"

    return f"{platform_label} Кукис {slot}"


def _slot_command(platform: str, slot: int) -> str | None:
    prefix = PLATFORM_COMMAND_PREFIXES.get(platform)

    if not prefix or slot == 0:
        return None

    return f"/{prefix}_{slot}"


def _slot_file_name(settings: Settings, platform: str, slot: int) -> str | None:
    path = get_cookie_slot_path(settings, platform, slot, require_existing=False)
    return path.name if path else None


def build_rotation_alert(settings: Settings, event: CookieRotationRecord) -> str:
    platform = event.platform
    platform_label = PLATFORM_LABELS.get(platform, platform)
    failed_slot = event.failed_slot
    next_slot = event.next_slot

    if failed_slot == 0:
        first_line = f"ГОСТЕВОЙ {platform_label.upper()} УМЕР"
        lived_line = f"гость для {platform_label.lower()} прожил {event.lived_count} запросов"
    else:
        first_line = f"{_slot_label(platform, failed_slot)} умер"
        lived_line = f"кукис_{failed_slot} для {platform_label.lower()} прожил {event.lived_count} запросов"

    lines = [
        first_line,
        f"Мы перешли на {_slot_label(platform, next_slot)}",
        "",
        lived_line,
    ]

    if failed_slot:
        file_name = _slot_file_name(settings, platform, failed_slot)
        command = _slot_command(platform, failed_slot)

        if file_name:
            lines.append(f"Замени файл: {file_name}")

        if command:
            lines.append(f"Команда: {command}")

    if event.reason:
        lines.extend(["", f"Причина: {_short_reason(event.reason)}"])

    return "\n".join(lines)


async def notify_cookie_rotation(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    settings: Settings,
    event: CookieRotationRecord,
) -> None:
    text = build_rotation_alert(settings, event)

    for admin_id in sorted(getattr(settings, "cookie_alert_admin_ids", None) or settings.admin_ids):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Cookie rotation alert failed | admin_id=%s platform=%s", admin_id, event.platform)


async def run_with_cookie_rotation(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    operation: Callable[[int], Any],
    platform: str | None = None,
    operation_name: str = "platform_request",
) -> CookieAuthResult:
    settings: Settings = context.application.bot_data["settings"]
    platform = platform_from_url_or_name(platform) or platform_from_url_or_name(url)

    if not platform:
        value = await asyncio.to_thread(operation, 0)
        return CookieAuthResult(value=value, platform=None, slot=None, auth_name=None)

    current_slot = get_auth_slot(settings, platform)
    tried_slots: set[int] = set()
    last_error: BaseException | None = None

    for _ in COOKIE_SLOTS:
        if current_slot in tried_slots:
            break

        if not is_cookie_slot_usable(settings, platform, current_slot):
            event = rotate_auth_slot(
                settings,
                platform=platform,
                failed_slot=current_slot,
                reason="cookie file missing or empty",
            )
            logger.warning(
                "Cookie slot preflight failed | operation=%s platform=%s failed_slot=%s next_slot=%s",
                operation_name,
                platform,
                current_slot,
                event.next_slot,
            )
            await notify_cookie_rotation(context=context, settings=settings, event=event)
            tried_slots.add(current_slot)
            current_slot = event.next_slot
            continue

        tried_slots.add(current_slot)

        try:
            value = await asyncio.to_thread(operation, current_slot)
            return CookieAuthResult(
                value=value,
                platform=platform,
                slot=current_slot,
                auth_name=get_auth_name(platform, current_slot),
            )

        except Exception as e:
            last_error = e

            if not is_auth_related_error(e):
                raise

            event = rotate_auth_slot(
                settings,
                platform=platform,
                failed_slot=current_slot,
                reason=_short_reason(e),
            )
            logger.warning(
                "Cookie slot rotated after auth error | operation=%s platform=%s failed_slot=%s next_slot=%s error=%s",
                operation_name,
                platform,
                current_slot,
                event.next_slot,
                _short_reason(e, 250),
            )
            await notify_cookie_rotation(context=context, settings=settings, event=event)
            current_slot = event.next_slot

    if last_error:
        raise last_error

    raise RuntimeError(f"No usable auth slot for {platform}")


def count_cookie_success(settings: Settings, platform: str | None, slot: int | None, amount: int = 1) -> None:
    increment_cookie_success(settings, platform, slot, amount=amount)


async def fetch_video_metadata_with_platform_auth(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    metadata_func: Callable[..., Any] | None = None,
) -> dict:
    settings: Settings = context.application.bot_data["settings"]

    if metadata_func is None:
        from app.downloader.metadata import fetch_metadata

        metadata_func = fetch_metadata

    result = await run_with_cookie_rotation(
        context=context,
        url=url,
        operation=lambda slot: metadata_func(settings, url, platform_auth_slot=slot),
        operation_name="fetch_video_metadata_with_platform_auth",
    )

    info = result.value

    if isinstance(info, dict):
        info["_platform_auth_name"] = result.auth_name
        info["_platform_auth_slot"] = result.slot

    return info


async def download_video_smart_with_platform_auth(
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    output_dir,
    info: dict,
    requested_quality: int | None,
    requested_audio_lang: str | None,
    download_func: Callable[..., Any] | None = None,
):
    settings: Settings = context.application.bot_data["settings"]

    if download_func is None:
        from app.downloader.legacy_youtube_downloader import download_video_smart_legacy

        download_func = download_video_smart_legacy

    result = await run_with_cookie_rotation(
        context=context,
        url=url,
        operation=lambda slot: download_func(
            settings,
            url,
            output_dir,
            info,
            requested_quality,
            requested_audio_lang,
            platform_auth_slot=slot,
        ),
        operation_name="download_video_smart_with_platform_auth",
    )

    file_path, downloaded_info, status = result.value

    if isinstance(downloaded_info, dict):
        downloaded_info["_platform_auth_name"] = result.auth_name
        downloaded_info["_platform_auth_slot"] = result.slot

    return file_path, downloaded_info, status
