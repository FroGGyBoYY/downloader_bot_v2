import asyncio
import inspect
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from telegram import Update
from telegram.ext import ContextTypes

from app.downloader.legacy_youtube_downloader import is_youtube_url_legacy
from app.services.legacy_youtube_service import start_legacy_youtube_flow
from app.services.download_service import (
    process_download_request,
    send_spotify_savers_promo,
    try_send_cached_download_request,
)

from app.downloader.metadata import try_fetch_metadata
from app.downloader import routing
from app.downloader import url_resolver

from app.downloader.routing import make_route_decision as routing_make_route_decision
from app.downloader.url_cleaner import clean_download_url
from app.db.groups_repo import record_group_activity
from app.db.users_repo import upsert_user
from app.services.cookie_auth_service import is_auth_related_error, run_with_cookie_rotation
from app.services.access_control_service import send_access_denied_if_needed
from app.services.required_subscriptions_service import send_required_subscriptions_if_needed

logger = logging.getLogger(__name__)


URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
METADATA_TIMEOUT_SECONDS = 35
GROUP_CHAT_TYPES = {"group", "supergroup"}
GROUP_LINK_COMMANDS = ("/download", "/dl")


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_external_music_service_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()

    if not host:
        return False

    if _host_matches(host, "music.youtube.com"):
        return False

    if _host_matches(host, "open.spotify.com") or _host_matches(host, "spotify.link"):
        return True

    if _host_matches(host, "music.apple.com") or _host_matches(host, "itunes.apple.com"):
        return True

    if _host_matches(host, "soundcloud.com"):
        return True

    if _host_matches(host, "vk.com") or _host_matches(host, "vk.ru"):
        return path.startswith("/audio") or "z=audio" in query

    if host.startswith("music.yandex.") or (
        (_host_matches(host, "yandex.ru") or _host_matches(host, "yandex.com"))
        and path.startswith("/music")
    ):
        return True

    music_domains = (
        "audiomack.com",
        "album.link",
        "apple.co",
        "bandcamp.com",
        "boom.ru",
        "deezer.com",
        "dzr.page.link",
        "jamendo.com",
        "listen.tidal.com",
        "music.amazon.com",
        "odesli.co",
        "song.link",
        "tidal.com",
        "zvuk.com",
        "zvuk.link",
    )

    return any(_host_matches(host, domain) for domain in music_domains)


def _is_youtube_music_playlist_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()

    if "music.youtube.com" not in host:
        return False

    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if path.startswith("/playlist"):
        return bool(query.get("list"))

    return bool(query.get("list")) and not query.get("v")


def _is_youtube_music_url(url: str | None) -> bool:
    if not url:
        return False

    return "music.youtube.com" in urlparse(str(url)).netloc.lower()


def _is_google_sorry_or_youtube_consent_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host in {"google.com", "www.google.com"} and path.startswith("/sorry"):
        return True

    return host == "consent.youtube.com"


def _keep_youtube_music_original_if_resolve_is_blocked(
    original_url: str,
    raw_resolved_url: str,
) -> str:
    if (
        _is_youtube_music_url(original_url)
        and _is_google_sorry_or_youtube_consent_url(raw_resolved_url)
    ):
        logger.warning(
            "YouTube Music resolve returned a block/consent page, using original URL | original=%s raw_resolved=%s",
            original_url,
            raw_resolved_url,
        )
        return original_url

    return raw_resolved_url


def extract_first_url(text: str | None) -> str | None:
    if not text:
        return None

    match = URL_RE.search(text)

    if not match:
        return None

    url = match.group(0).strip()

    # Telegram иногда цепляет точку/скобку в конец
    url = url.rstrip(".,);]}>")

    return url


def _enum_value(value: Any) -> str:
    if value is None:
        return "none"

    return getattr(value, "value", str(value))


def _get_setting(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("settings")


def _get_user_language_code(context: ContextTypes.DEFAULT_TYPE, user) -> str:
    settings = _get_setting(context)

    if user:
        try:
            from app.db.users_repo import get_user_language

            try:
                lang = get_user_language(settings, user.id)
            except TypeError:
                lang = get_user_language(user.id)

            if lang:
                return str(lang)
        except Exception:
            pass

        if getattr(user, "language_code", None):
            return str(user.language_code)

    return "en"


def _is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and str(chat.type) in GROUP_CHAT_TYPES)


def _group_message_targets_bot(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if not _is_group_chat(update):
        return True

    message = update.message

    if not message:
        return False

    text = (message.text or message.caption or "").strip()
    lowered = text.lower()

    for command in GROUP_LINK_COMMANDS:
        if lowered == command or lowered.startswith(command + " ") or lowered.startswith(command + "@"):
            return True

    bot_username = (
        context.application.bot_data.get("bot_username")
        or getattr(context.bot, "username", None)
    )

    if bot_username and f"@{str(bot_username).lower()}" in lowered:
        return True

    bot_id = context.application.bot_data.get("bot_id") or getattr(context.bot, "id", None)
    reply = message.reply_to_message
    reply_user = getattr(reply, "from_user", None) if reply else None

    if bot_id and reply_user and reply_user.id == bot_id:
        return True

    return False


async def _resolve_url_async(settings, url: str) -> str:
    """
    Аккуратная обёртка над url_resolver.

    ВАЖНО:
    Сначала пробуем resolver(url), потому что большинство resolver-функций
    принимают именно ссылку первым аргументом.
    """
    resolver = (
        getattr(url_resolver, "resolve_url", None)
        or getattr(url_resolver, "resolve_redirect_url", None)
        or getattr(url_resolver, "resolve_final_url", None)
    )

    if not resolver:
        return url

    async def _call_async():
        try:
            return await resolver(url)
        except TypeError:
            try:
                return await resolver(url, settings)
            except TypeError:
                return await resolver(settings, url)

    def _call_sync():
        try:
            return resolver(url)
        except TypeError:
            try:
                return resolver(url, settings)
            except TypeError:
                return resolver(settings, url)

    try:
        if inspect.iscoroutinefunction(resolver):
            resolved = await _call_async()
        else:
            resolved = await asyncio.to_thread(_call_sync)

        if not isinstance(resolved, str):
            logger.warning(
                "URL resolver returned non-string | url=%s resolved_type=%s resolved=%s",
                url,
                type(resolved).__name__,
                resolved,
            )
            return url

        if not resolved.startswith(("http://", "https://")):
            logger.warning(
                "URL resolver returned invalid URL | url=%s resolved=%s",
                url,
                resolved,
            )
            return url

        return resolved

    except Exception:
        logger.exception("URL resolve failed | url=%s", url)
        return url


def _make_url_hint(original_url: str, resolved_url: str):
    maker = (
        getattr(routing, "make_url_route_hint", None)
        or getattr(routing, "build_url_route_hint", None)
        or getattr(routing, "create_url_route_hint", None)
    )

    if not maker:
        raise RuntimeError("No URL hint builder found in app.downloader.routing")

    try:
        return maker(original_url, resolved_url)
    except TypeError:
        try:
            return maker(original_url=original_url, resolved_url=resolved_url)
        except TypeError:
            return maker(original_url)


def _make_route_decision(
    original_url: str,
    resolved_url: str | None,
    info: dict | None,
    metadata_error: Exception | None = None,
):
    """
    Важно:
    routing.make_route_decision сам внутри строит UrlRouteHint.
    Поэтому сюда нельзя передавать hint вместо URL.
    """
    maker = routing_make_route_decision

    try:
        return maker(
            original_url=original_url,
            resolved_url=resolved_url,
            info=info,
            metadata_error=metadata_error,
        )
    except TypeError:
        pass

    try:
        return maker(
            original_url=original_url,
            resolved_url=resolved_url,
            info=info,
        )
    except TypeError:
        pass

    try:
        return maker(
            original_url,
            resolved_url,
            info,
            metadata_error,
        )
    except TypeError:
        pass

    try:
        return maker(
            original_url,
            resolved_url,
            info,
        )
    except TypeError:
        pass

    return maker(original_url, resolved_url)


async def _fetch_metadata_async(context: ContextTypes.DEFAULT_TYPE, settings, url: str):
    def _operation(slot: int):
        info, error = try_fetch_metadata(settings, url, platform_auth_slot=slot)

        if info is None and is_auth_related_error(error):
            raise RuntimeError(error)

        return info, error

    result = await asyncio.wait_for(
        run_with_cookie_rotation(
            context=context,
            url=url,
            operation=_operation,
            operation_name="metadata",
        ),
        timeout=METADATA_TIMEOUT_SECONDS,
    )

    return result.value

async def link_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    text = update.message.text or update.message.caption or ""
    url = extract_first_url(text)

    if not url:
        return

    if not _group_message_targets_bot(update, context):
        logger.info(
            "Group link ignored because bot was not targeted | user_id=%s chat_id=%s url=%s",
            update.effective_user.id if update.effective_user else None,
            update.effective_chat.id if update.effective_chat else None,
            url,
        )
        return

    settings = _get_setting(context)
    user = update.effective_user
    chat_id = update.effective_chat.id
    language_code = _get_user_language_code(context, user)
    upsert_user(settings, user)

    if _is_group_chat(update):
        try:
            record_group_activity(settings, update.effective_chat)
        except Exception:
            logger.exception("Could not record group activity | chat_id=%s", chat_id)

    if await send_access_denied_if_needed(
        context=context,
        chat_id=chat_id,
        user_id=user.id if user else None,
        reply_to_message_id=update.message.message_id,
    ):
        logger.info(
            "Link blocked by access control | user_id=%s url=%s",
            user.id if user else None,
            url,
        )
        return

    if _is_external_music_service_url(url):
        await send_spotify_savers_promo(
            context=context,
            chat_id=chat_id,
            user_id=user.id if user else None,
            original_url=url,
            resolved_url=url,
            reply_to_message_id=update.message.message_id,
            skip_for_subscribers=False,
        )
        logger.info(
            "External music link redirected to Spotify Savers bot | user_id=%s url=%s",
            user.id if user else None,
            url,
        )
        return

    if await send_required_subscriptions_if_needed(
        context=context,
        chat_id=chat_id,
        user_id=user.id if user else None,
        reply_to_message_id=update.message.message_id,
    ):
        logger.info(
            "Link blocked by required subscriptions | user_id=%s url=%s",
            user.id if user else None,
            url,
        )
        return

    logger.info(
        "Accepted link | user_id=%s url=%s language=%s",
        user.id if user else None,
        url,
        language_code,
    )

    # ============================================================
    # YouTube полностью уходит в legacy-flow.
    # music.youtube.com НЕ перехватываем, чтобы YouTube Music
    # мог идти через обычную audio-логику.
    # ============================================================
    if is_youtube_url_legacy(url) and "music.youtube.com" not in url.lower():
        await start_legacy_youtube_flow(
            update=update,
            context=context,
            url=url,
            language_code=language_code,
        )
        return

    # ============================================================
    # Все остальные платформы: TikTok / Instagram / Pinterest / etc.
    # ============================================================
    raw_resolved_url = await _resolve_url_async(settings, url)
    raw_resolved_url = _keep_youtube_music_original_if_resolve_is_blocked(url, raw_resolved_url)

    # Чистим resolved URL для скачивания.
    # Особенно важно для TikTok:
    # было: .../video/123?_r=1&_t=...
    # надо: .../video/123
    resolved_url = clean_download_url(raw_resolved_url) or raw_resolved_url
    url_for_download = clean_download_url(resolved_url or url) or (resolved_url or url)

    logger.info(
        "URL prepared | user_id=%s original=%s raw_resolved=%s clean_resolved=%s download=%s",
        user.id if user else None,
        url,
        raw_resolved_url,
        resolved_url,
        url_for_download,
    )

    # Для классификатора тоже даём чистую ссылку.
    hint = _make_url_hint(url, url_for_download)

    logger.info(
        "URL hint | user_id=%s platform=%s content_type=%s action=%s confidence=%s reason=%s original=%s resolved=%s download=%s",
        user.id if user else None,
        _enum_value(getattr(hint, "platform", None)),
        _enum_value(getattr(hint, "content_type", None)),
        _enum_value(getattr(hint, "action", None)),
        getattr(hint, "confidence", None),
        getattr(hint, "reason", None),
        url,
        resolved_url,
        url_for_download,
    )

    early_route = _make_route_decision(url, url_for_download, None, "early_cache_probe")

    if await try_send_cached_download_request(
        context=context,
        chat_id=chat_id,
        user=user,
        language_code=language_code,
        original_url=url,
        resolved_url=url_for_download,
        route=early_route,
        reply_to_message_id=update.message.message_id,
    ):
        logger.info(
            "Link served from early cache before metadata | user_id=%s url=%s",
            user.id if user else None,
            url,
        )
        return

    info = None
    metadata_error = None

    # ВАЖНО: metadata тоже читаем по чистой ссылке.
    metadata_url = url_for_download

    if (
        _enum_value(getattr(hint, "platform", None)) == "instagram"
        and _enum_value(getattr(hint, "content_type", None)) == "story"
    ):
        metadata_error = "metadata_skipped_instagram_story"
        logger.info("Metadata skipped for Instagram story | url=%s", metadata_url)
    elif _is_youtube_music_playlist_url(metadata_url):
        metadata_error = "metadata_skipped_youtube_music_playlist"
        logger.info("Metadata skipped for YouTube Music playlist | url=%s", metadata_url)
    else:
        try:
            info, metadata_error = await _fetch_metadata_async(context, settings, metadata_url)
        except asyncio.TimeoutError:
            metadata_error = f"metadata_timeout_{METADATA_TIMEOUT_SECONDS}s"
            logger.warning(
                "Metadata timeout | url=%s | raw_resolved=%s | download=%s",
                url,
                raw_resolved_url,
                url_for_download,
            )
        except Exception as e:
            metadata_error = f"{type(e).__name__}: {e}"
            logger.exception(
                "Metadata crashed | url=%s | raw_resolved=%s | download=%s | error=%s",
                url,
                raw_resolved_url,
                url_for_download,
                e,
            )

    # Route decision тоже строим по чистой ссылке.
    route = _make_route_decision(url, url_for_download, info, metadata_error)

    logger.info(
        "Route decision | user_id=%s platform=%s content_type=%s action=%s metadata=%s reason=%s title=%s photos=%s videos=%s audio=%s entries=%s",
        user.id if user else None,
        _enum_value(getattr(route, "platform", None)),
        _enum_value(getattr(route, "content_type", None)),
        _enum_value(getattr(route, "action", None)),
        getattr(route, "metadata_status", None),
        getattr(route, "reason", None),
        getattr(route, "title", None),
        getattr(route, "photos_count", 0),
        getattr(route, "videos_count", 0),
        getattr(route, "audio_count", 0),
        getattr(route, "entries_count", 0),
    )

    await process_download_request(
        context=context,
        chat_id=chat_id,
        user=user,
        language_code=language_code,
        original_url=url,
        resolved_url=url_for_download,
        route=route,
        reply_to_message_id=update.message.message_id,
    )
