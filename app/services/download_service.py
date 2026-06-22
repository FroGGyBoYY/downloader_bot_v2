import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardMarkup, User
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.cache_repo import get_cached_bundle, save_cached_item, touch_cache_bundle
from app.db.downloads_repo import add_download_item, create_download_request, update_download_request
from app.db.users_repo import (
    get_full_name,
    increment_user_cache_hit,
    increment_user_download,
    increment_user_request,
    is_user_subscribed,
)
from app.downloader.cache_keys import build_bundle_key, build_cache_key, build_source_key, build_variant_key
from app.downloader.download_engine import DownloadedMedia, download_media_bundle
from app.downloader.routing import RouteDecision
from app.services.access_control_service import send_access_denied_if_needed
from app.services.ads_service import maybe_send_after_download_ad
from app.services.cookie_auth_service import count_cookie_success, run_with_cookie_rotation
from app.services.proxy_rotation_service import run_with_proxy_rotation_sync
from app.telegram_ui.captions import CaptionPayload, build_content_caption, build_media_caption
from app.telegram_ui.button_styles import build_styled_url_button
from app.telegram_ui.messages import send_text
from app.telegram_ui.sender import SentTelegramFile, send_cached_media, send_local_media
from app.telegram_ui.user_messages import processing_message, public_download_error_message
from urllib.parse import urlparse
from app.texts.keys import TextKey

from contextlib import ExitStack
from telegram import InputMediaAudio, InputMediaPhoto, InputMediaVideo
from telegram.error import TelegramError, TimedOut, NetworkError

import subprocess

import json
import httpx

logger = logging.getLogger(__name__)

FREE_AUDIO_PLAYLIST_LIMIT = 50
SPOTIFY_SAVERS_BOT = "@spotify_savers_bot"
SPOTIFY_SAVERS_URL = "https://t.me/spotify_savers_bot"


def _url_host_contains(url: str | None, value: str) -> bool:
    if not url:
        return False

    try:
        return value in urlparse(str(url)).netloc.lower()
    except Exception:
        return False


def _is_youtube_music_source(original_url: str | None, resolved_url: str | None) -> bool:
    return (
        _url_host_contains(original_url, "music.youtube.com")
        or _url_host_contains(resolved_url, "music.youtube.com")
    )


def _album_track_limit(
    *,
    settings: Settings,
    user_id: int | None,
    route: RouteDecision,
    original_url: str | None,
    resolved_url: str | None,
) -> int | None:
    platform = getattr(route.platform, "value", str(route.platform))
    action = getattr(route.action, "value", str(route.action))

    if platform != "youtube" or action != "download_album":
        return None

    if not _is_youtube_music_source(original_url, resolved_url):
        return None

    if is_user_subscribed(settings, user_id):
        return None

    return FREE_AUDIO_PLAYLIST_LIMIT


def _album_limit_variant(limit: int | None) -> str | None:
    return f"limit{limit}" if limit else None


def _rows_include_youtube_music_audio(rows, original_url: str | None, resolved_url: str | None) -> bool:
    if not _is_youtube_music_source(original_url, resolved_url):
        return False

    return any(
        str(_row_get(row, "media_type") or "").lower() == "audio"
        or str(_row_get(row, "tg_send_type") or "").lower() == "audio"
        for row in rows or []
    )


def _sent_entries_include_youtube_music_audio(
    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]],
    original_url: str | None,
    resolved_url: str | None,
) -> bool:
    if not _is_youtube_music_source(original_url, resolved_url):
        return False

    return any(getattr(item, "media_type", None) == "audio" for item, _ in sent_entries)


async def send_spotify_savers_promo(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    original_url: str | None,
    resolved_url: str | None,
    reply_to_message_id: int | None = None,
    skip_for_subscribers: bool = True,
) -> None:
    settings: Settings = context.application.bot_data["settings"]

    if skip_for_subscribers and is_user_subscribed(settings, user_id):
        return

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Любишь быстро скачивать музыку? Для Spotify, YouTube Music "
                f"и других сервисов есть отдельный бот {SPOTIFY_SAVERS_BOT}."
            ),
            reply_markup=InlineKeyboardMarkup([[
                build_styled_url_button(
                    SPOTIFY_SAVERS_BOT,
                    url=SPOTIFY_SAVERS_URL,
                    style_config="green",
                )
            ]]),
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception(
            "Spotify Savers promo failed | user_id=%s chat_id=%s original=%s resolved=%s",
            user_id,
            chat_id,
            original_url,
            resolved_url,
        )


async def _maybe_send_spotify_savers_promo(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    original_url: str | None,
    resolved_url: str | None,
    has_youtube_music_audio: bool,
) -> None:
    if not has_youtube_music_audio:
        return

    await send_spotify_savers_promo(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        original_url=original_url,
        resolved_url=resolved_url,
    )

def _is_generic_instagram_story_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    # /stories/username/ - динамическая ссылка на текущие сторис.
    # Ее лучше не кешировать, потому что сторис меняются.
    return (
        len(parts) == 2
        and parts[0].lower() == "stories"
    )


def _is_cache_allowed(
    *,
    route: RouteDecision,
    original_url: str,
    resolved_url: str | None,
) -> bool:
    platform = getattr(route.platform, "value", str(route.platform))
    url = resolved_url or original_url

    if platform == "instagram" and _is_generic_instagram_story_url(url):
        return False

    return True


def _get_complete_cached_rows(rows) -> list:
    rows = list(rows or [])

    if not rows:
        return []

    if any(not row["tg_file_id"] or not row["tg_send_type"] for row in rows):
        return []

    try:
        expected_total = int(rows[0]["item_total"] or len(rows))
    except Exception:
        expected_total = len(rows)

    if expected_total != len(rows):
        return []

    indexes = []

    for row in rows:
        try:
            indexes.append(int(row["item_index"]))
        except Exception:
            return []

    if indexes != list(range(len(rows))):
        return []

    return rows


def _extract_sent_file_from_message(message, media_type: str) -> SentTelegramFile:
    if media_type == "photo" and message.photo:
        largest = message.photo[-1]
        return SentTelegramFile(
            file_id=largest.file_id,
            file_unique_id=largest.file_unique_id,
            send_type="photo",
        )

    if media_type == "video" and message.video:
        return SentTelegramFile(
            file_id=message.video.file_id,
            file_unique_id=message.video.file_unique_id,
            send_type="video",
        )

    if media_type == "audio" and message.audio:
        return SentTelegramFile(
            file_id=message.audio.file_id,
            file_unique_id=message.audio.file_unique_id,
            send_type="audio",
        )

    if message.document:
        return SentTelegramFile(
            file_id=message.document.file_id,
            file_unique_id=message.document.file_unique_id,
            send_type="document",
        )

    raise RuntimeError("Telegram did not return file object for cached save")


def _audio_album_caption(title: str | None) -> str:
    return (str(title or "Album").strip() or "Album")[:1024]


def _empty_caption() -> CaptionPayload:
    return CaptionPayload(text="", entities=[])


def _row_get(row, key: str, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _clean_album_title(value: str | None) -> str | None:
    text = str(value or "").replace("\n", " ").strip()
    text = " ".join(text.split())
    return text or None


def _album_title_from_audio_items(audio_items: list, fallback: str | None = None) -> str | None:
    for item in audio_items or []:
        title = _clean_album_title(getattr(item, "album_title", None))

        if title and title != "Media":
            return title

    return _clean_album_title(fallback)


def _album_title_from_cached_rows(rows, fallback: str | None = None) -> str | None:
    for row in rows or []:
        title = _clean_album_title(_row_get(row, "album_title"))

        if title and title != "Media":
            return title

    return _clean_album_title(fallback)


def _content_caption(
    *,
    settings: Settings,
    title: str | None,
    platform: str,
    source_url: str | None,
    media_type: str | None,
    quality: int | None = None,
    audio_label: str | None = None,
    audio_lang: str | None = None,
    item_index: int = 0,
    item_total: int = 1,
) -> CaptionPayload:
    include_youtube_video_meta = platform == "youtube" and media_type == "video"

    return build_content_caption(
        title=title,
        platform=platform,
        bot_username=settings.bot_username_text,
        source_url=source_url,
        quality=quality if include_youtube_video_meta else None,
        audio_label=audio_label if include_youtube_video_meta else None,
        audio_lang=audio_lang,
        media_type=media_type,
        item_index=item_index,
        item_total=item_total,
        include_quality=include_youtube_video_meta,
        include_audio=include_youtube_video_meta,
    )


def _looks_like_tiktok_generated_title(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return bool(re.fullmatch(r"tiktok\s+video\s+#?\d+", text))


def _caption_title_for_media(
    *,
    platform: str,
    media_type: str | None,
    route_title: str | None,
    item_title: str | None,
) -> str | None:
    if (
        platform == "tiktok"
        and media_type == "video"
        and item_title
        and (
            not route_title
            or route_title == "Media"
            or _looks_like_tiktok_generated_title(route_title)
        )
    ):
        return item_title

    if (
        platform == "tiktok"
        and media_type == "video"
        and route_title
        and _looks_like_tiktok_generated_title(route_title)
    ):
        return item_title or route_title

    return route_title or item_title


def _is_stale_youtube_music_album_cache(rows, platform: str) -> bool:
    if platform != "youtube":
        return False

    rows = list(rows or [])

    if not any(
        _is_youtube_music_source(
            _row_get(row, "original_url"),
            _row_get(row, "resolved_url"),
        )
        for row in rows
    ):
        return False

    audio_rows = [
        row for row in rows
        if row["media_type"] == "audio" and row["tg_send_type"] == "audio"
    ]

    if len(audio_rows) != len(rows):
        return True

    if len(audio_rows) < 2:
        return False

    titles = {
        str(row["title"] or "").strip()
        for row in audio_rows
        if str(row["title"] or "").strip()
    }

    return len(titles) <= 1


async def _send_cached_audio_album(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    rows,
    album_title: str,
    source_url: str | None,
    start_sent_count: int,
    reply_to_message_id: int | None,
) -> int:
    rows = list(rows or [])
    sent_count = 0
    processed_rows = 0
    total_rows = len(rows)

    for chunk in _chunk_items(rows, 10):
        first_message = start_sent_count + sent_count == 0

        if len(chunk) < 2:
            row = chunk[0]
            is_last_album_item = processed_rows == total_rows - 1
            caption_payload = _content_caption(
                settings=settings,
                title=album_title,
                platform=row["platform"] or "youtube",
                source_url=row["original_url"] or row["resolved_url"] or source_url,
                media_type="audio",
                item_index=0,
                item_total=total_rows,
            ) if is_last_album_item else _empty_caption()

            await send_cached_media(
                settings=settings,
                bot=context.bot,
                chat_id=chat_id,
                tg_file_id=row["tg_file_id"],
                send_type=row["tg_send_type"],
                caption=caption_payload.text,
                caption_entities=caption_payload.entities,
                reply_to_message_id=reply_to_message_id if first_message else None,
            )

            sent_count += 1
            processed_rows += 1
            continue

        media_group = []

        for item_index, row in enumerate(chunk):
            caption = None
            caption_entities = None
            is_last_album_item = processed_rows + item_index == total_rows - 1

            if is_last_album_item:
                caption_payload = _content_caption(
                    settings=settings,
                    title=album_title,
                    platform=row["platform"] or "youtube",
                    source_url=row["original_url"] or row["resolved_url"] or source_url,
                    media_type="audio",
                    item_index=0,
                    item_total=total_rows,
                )
                caption = caption_payload.text
                caption_entities = caption_payload.entities

            media_group.append(
                InputMediaAudio(
                    media=row["tg_file_id"],
                    caption=caption,
                    caption_entities=caption_entities,
                    title=row["title"] or None,
                    performer=row["author"] or None,
                    duration=row["duration"],
                )
            )

        try:
            await context.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                reply_to_message_id=reply_to_message_id if first_message else None,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )

            sent_count += len(chunk)
            processed_rows += len(chunk)

        except (TelegramError, TimedOut, NetworkError):
            logger.exception("send_cached_audio media_group failed, fallback to one-by-one")

            for item_index, row in enumerate(chunk):
                first_fallback_message = start_sent_count + sent_count == 0 and item_index == 0
                is_last_album_item = processed_rows + item_index == total_rows - 1
                caption_payload = _content_caption(
                    settings=settings,
                    title=album_title,
                    platform=row["platform"] or "youtube",
                    source_url=row["original_url"] or row["resolved_url"] or source_url,
                    media_type="audio",
                    item_index=0,
                    item_total=total_rows,
                ) if is_last_album_item else _empty_caption()

                await send_cached_media(
                    settings=settings,
                    bot=context.bot,
                    chat_id=chat_id,
                    tg_file_id=row["tg_file_id"],
                    send_type=row["tg_send_type"],
                    caption=caption_payload.text,
                    caption_entities=caption_payload.entities,
                    reply_to_message_id=reply_to_message_id if first_fallback_message else None,
                )

                sent_count += 1
                processed_rows += 1

    return sent_count


async def _send_cached_bundle_fast(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    rows,
    title: str,
    platform: str,
    quality: int | None,
    audio_label: str | None,
    audio_lang: str | None,
    source_url: str | None,
    reply_to_message_id: int | None,
) -> int:
    rows = list(rows or [])

    if not rows:
        return 0

    sent_count = 0
    item_total = len(rows)

    visual_rows = [
        row for row in rows
        if row["tg_send_type"] in {"photo", "video"}
    ]

    audio_rows = [
        row for row in rows
        if row["tg_send_type"] == "audio"
    ]

    other_rows = [
        row for row in rows
        if row["tg_send_type"] not in {"photo", "video", "audio"}
    ]

    # 1. Если есть 2+ фото/видео - отправляем группой, а не по одному.
    if len(visual_rows) >= 2:
        chunks = _chunk_items(visual_rows, 10)

        for chunk_index, chunk in enumerate(chunks):
            # Если последний chunk из 1 элемента - Telegram media_group не примет.
            if len(chunk) < 2:
                row = chunk[0]

                caption_payload = _content_caption(
                    settings=settings,
                    title=_caption_title_for_media(
                        platform=row["platform"] or platform,
                        media_type=row["media_type"],
                        route_title=title,
                        item_title=row["title"],
                    ),
                    platform=row["platform"] or platform,
                    source_url=row["original_url"] or row["resolved_url"] or source_url,
                    media_type=row["media_type"],
                    quality=quality,
                    audio_label=audio_label,
                    audio_lang=audio_lang,
                    item_index=sent_count,
                    item_total=item_total,
                )

                await send_cached_media(
                    settings=settings,
                    bot=context.bot,
                    chat_id=chat_id,
                    tg_file_id=row["tg_file_id"],
                    send_type=row["tg_send_type"],
                    caption=caption_payload.text,
                    caption_entities=caption_payload.entities,
                    reply_to_message_id=reply_to_message_id if sent_count == 0 else None,
                )

                sent_count += 1
                continue

            media_group = []

            for item_index, row in enumerate(chunk):
                caption = None
                caption_entities = None

                if sent_count == 0 and item_index == 0:
                    caption_payload = _content_caption(
                        settings=settings,
                        title=_caption_title_for_media(
                            platform=row["platform"] or platform,
                            media_type=row["media_type"],
                            route_title=title,
                            item_title=row["title"],
                        ),
                        platform=row["platform"] or platform,
                        source_url=row["original_url"] or row["resolved_url"] or source_url,
                        media_type=row["media_type"],
                        quality=quality,
                        audio_label=audio_label,
                        audio_lang=audio_lang,
                        item_index=0,
                        item_total=item_total,
                    )
                    caption = caption_payload.text
                    caption_entities = caption_payload.entities

                if row["tg_send_type"] == "photo":
                    media_group.append(
                        InputMediaPhoto(
                            media=row["tg_file_id"],
                            caption=caption,
                            caption_entities=caption_entities,
                        )
                    )

                elif row["tg_send_type"] == "video":
                    media_group.append(
                        InputMediaVideo(
                            media=row["tg_file_id"],
                            caption=caption,
                            caption_entities=caption_entities,
                            supports_streaming=True,
                        )
                    )

            await context.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                reply_to_message_id=reply_to_message_id if sent_count == 0 else None,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )

            sent_count += len(chunk)

    elif len(visual_rows) == 1:
        row = visual_rows[0]

        caption_payload = _content_caption(
            settings=settings,
            title=_caption_title_for_media(
                platform=row["platform"] or platform,
                media_type=row["media_type"],
                route_title=title,
                item_title=row["title"],
            ),
            platform=row["platform"] or platform,
            source_url=row["original_url"] or row["resolved_url"] or source_url,
            media_type=row["media_type"],
            quality=quality,
            audio_label=audio_label,
            audio_lang=audio_lang,
            item_index=0,
            item_total=item_total,
        )

        await send_cached_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            tg_file_id=row["tg_file_id"],
            send_type=row["tg_send_type"],
            caption=caption_payload.text,
            caption_entities=caption_payload.entities,
            reply_to_message_id=reply_to_message_id,
        )

        sent_count += 1

    # 2. Аудио/документы отправляем после альбома.
    if len(audio_rows) >= 2:
        album_title = _album_title_from_cached_rows(audio_rows, title) or title

        sent_count += await _send_cached_audio_album(
            settings=settings,
            context=context,
            chat_id=chat_id,
            rows=audio_rows,
            album_title=album_title,
            source_url=source_url,
            start_sent_count=sent_count,
            reply_to_message_id=reply_to_message_id,
        )

    else:
        other_rows = audio_rows + other_rows

    for row in other_rows:
        caption_payload = _content_caption(
            settings=settings,
            title=_caption_title_for_media(
                platform=row["platform"] or platform,
                media_type=row["media_type"],
                route_title=title,
                item_title=row["title"],
            ),
            platform=row["platform"] or platform,
            source_url=row["original_url"] or row["resolved_url"] or source_url,
            media_type=row["media_type"],
            quality=quality,
            audio_label=audio_label,
            audio_lang=audio_lang,
            item_index=sent_count,
            item_total=item_total,
        )

        await send_cached_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            tg_file_id=row["tg_file_id"],
            send_type=row["tg_send_type"],
            caption=caption_payload.text,
            caption_entities=caption_payload.entities,
            reply_to_message_id=None if sent_count > 0 else reply_to_message_id,
        )

        sent_count += 1

    touch_cache_bundle(settings, rows[0]["bundle_key"])

    if user_id:
        increment_user_cache_hit(settings, user_id)

    return sent_count


async def try_send_cached_download_request(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user,
    language_code: str,
    original_url: str,
    resolved_url: str | None,
    route,
    reply_to_message_id: int | None = None,
    quality: int | None = None,
    audio_lang: str | None = None,
    audio_label: str | None = None,
) -> bool:
    settings = context.application.bot_data["settings"]
    platform = getattr(route.platform, "value", str(route.platform))
    content_type = getattr(route.content_type, "value", str(route.content_type))
    action = getattr(route.action, "value", str(route.action))
    title = getattr(route, "title", None) or "Media"
    user_id = getattr(user, "id", None)

    cache_allowed = _is_cache_allowed(
        route=route,
        original_url=original_url,
        resolved_url=resolved_url,
    )

    if not cache_allowed:
        return False

    album_item_limit = _album_track_limit(
        settings=settings,
        user_id=user_id,
        route=route,
        original_url=original_url,
        resolved_url=resolved_url,
    )
    source_key = build_source_key(route.platform, original_url, resolved_url)
    variant_key = build_variant_key(
        action=route.action,
        quality=quality,
        audio_lang=audio_lang,
        media_type=_album_limit_variant(album_item_limit),
    )
    bundle_key = build_bundle_key(source_key, variant_key)

    try:
        cached_rows = _get_complete_cached_rows(
            get_cached_bundle(settings, bundle_key)
        )

        if cached_rows and _is_stale_youtube_music_album_cache(cached_rows, platform):
            logger.info(
                "Early media cache STALE | user_id=%s bundle_key=%s reason=%s",
                user_id,
                bundle_key,
                "youtube_music_album_duplicate_titles",
            )
            return False

        if not cached_rows:
            logger.info(
                "Early media cache MISS | user_id=%s bundle_key=%s",
                user_id,
                bundle_key,
            )
            return False

        if title == "Media":
            if len(cached_rows) >= 2 and platform == "youtube":
                title = _album_title_from_cached_rows(cached_rows, title) or title
            else:
                title = str(cached_rows[0]["title"] or "").strip() or title

    except Exception:
        logger.exception(
            "Early media cache check failed | user_id=%s bundle_key=%s",
            user_id,
            bundle_key,
        )
        return False

    request_id = None

    if user_id:
        try:
            increment_user_request(settings, user_id)
            request_id = create_download_request(
                settings,
                user_id=user_id,
                username=getattr(user, "username", None),
                full_name=get_full_name(user),
                language_code=language_code,
                original_url=original_url,
                resolved_url=resolved_url,
                platform=platform,
                content_type=content_type,
                action=action,
                source_key=source_key,
                variant_key=variant_key,
                bundle_key=bundle_key,
                title=title,
                requested_quality=quality,
                requested_audio_lang=audio_lang,
                status="started",
            )
        except Exception:
            logger.exception("Could not create early cache-hit request row | user_id=%s url=%s", user_id, original_url)

    logger.info(
        "Early media cache HIT | user_id=%s bundle_key=%s items=%s",
        user_id,
        bundle_key,
        len(cached_rows),
    )

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="upload_document")
    except Exception:
        pass

    sent_count = await _send_cached_bundle_fast(
        settings=settings,
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        rows=cached_rows,
        title=title,
        platform=platform,
        quality=quality,
        audio_label=audio_label,
        audio_lang=audio_lang,
        source_url=original_url or resolved_url,
        reply_to_message_id=reply_to_message_id,
    )

    if user_id:
        increment_user_download(settings, user_id)

    if request_id:
        try:
            for index, row in enumerate(cached_rows):
                add_download_item(
                    settings,
                    request_id=request_id,
                    cache_key=row["cache_key"],
                    item_index=index,
                    media_type=row["media_type"],
                    status="sent",
                    cache_status="hit",
                    tg_file_id=row["tg_file_id"],
                    tg_send_type=row["tg_send_type"],
                    file_size=row["file_size"],
                    width=row["width"],
                    height=row["height"],
                    duration=row["duration"],
                )

            update_download_request(
                settings,
                request_id,
                status="sent",
                cache_status="hit",
                items_total=len(cached_rows),
                items_sent=sent_count,
            )
        except Exception:
            logger.exception("Could not write early cache-hit request items | request_id=%s", request_id)

    await maybe_send_after_download_ad(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
    )

    await _maybe_send_spotify_savers_promo(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        original_url=original_url,
        resolved_url=resolved_url,
        has_youtube_music_audio=_rows_include_youtube_music_audio(cached_rows, original_url, resolved_url),
    )

    return True


def _save_sent_entries_to_cache(
    *,
    settings: Settings,
    route: RouteDecision,
    original_url: str,
    resolved_url: str | None,
    source_key: str,
    variant_key: str,
    bundle_key: str,
    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]],
    title: str,
    quality: int | None,
    audio_lang: str | None,
) -> None:
    item_total = len(sent_entries)

    for index, (item, sent_file) in enumerate(sent_entries):
        cache_key = build_cache_key(bundle_key, index)

        save_cached_item(
            settings,
            cache_key=cache_key,
            bundle_key=bundle_key,
            source_key=source_key,
            variant_key=variant_key,
            platform=route.platform.value,
            content_type=route.content_type.value,
            media_type=item.media_type,
            original_url=original_url,
            resolved_url=resolved_url,
            title=item.title or title,
            author=item.author,
            item_index=index,
            item_total=item_total,
            tg_file_id=sent_file.file_id,
            tg_file_unique_id=sent_file.file_unique_id,
            tg_send_type=sent_file.send_type,
            file_size=item.file_size,
            width=item.width,
            height=item.height,
            duration=item.duration,
            quality=quality,
            audio_lang=audio_lang,
            album_title=getattr(item, "album_title", None),
        )


async def _send_audio_items_and_collect(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    audio_items: list,
    caption: str | None = None,
    caption_entities: list | None = None,
    reply_to_message_id: int | None = None,
    group_as_album: bool = False,
) -> list[tuple[DownloadedMedia, SentTelegramFile]]:
    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]] = []

    if group_as_album and len(audio_items) >= 2:
        album_caption = (caption or "Album")[:1024]
        album_caption_entities = caption_entities or []
        total_audio_items = len(audio_items)
        processed_audio_items = 0

        for chunk in _chunk_items(audio_items, 10):
            first_message = not sent_entries

            if len(chunk) < 2:
                item = chunk[0]
                path = Path(item.path)
                is_last_album_item = processed_audio_items == total_audio_items - 1

                sent_file = await send_local_media(
                    settings=settings,
                    bot=context.bot,
                    chat_id=chat_id,
                    file_path=path,
                    media_type="audio",
                    caption=album_caption if is_last_album_item else "",
                    caption_entities=album_caption_entities if is_last_album_item else None,
                    title=item.title,
                    performer=item.author,
                    duration=item.duration,
                    width=item.width,
                    height=item.height,
                    reply_to_message_id=reply_to_message_id if first_message else None,
                )

                sent_entries.append((item, sent_file))
                processed_audio_items += 1
                continue

            try:
                with ExitStack() as stack:
                    media_group = []

                    for item_index, item in enumerate(chunk):
                        path = Path(item.path)
                        file_obj = stack.enter_context(open(path, "rb"))
                        is_last_album_item = processed_audio_items + item_index == total_audio_items - 1

                        media_group.append(
                            InputMediaAudio(
                                media=file_obj,
                                caption=album_caption if is_last_album_item else None,
                                caption_entities=album_caption_entities if is_last_album_item else None,
                                title=item.title,
                                performer=item.author,
                                duration=item.duration,
                                filename=path.name,
                            )
                        )

                    messages = await context.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        reply_to_message_id=reply_to_message_id if first_message else None,
                        read_timeout=settings.send_read_timeout,
                        write_timeout=settings.send_write_timeout,
                        connect_timeout=settings.send_connect_timeout,
                        pool_timeout=settings.send_pool_timeout,
                    )

                for item, message in zip(chunk, messages):
                    sent_file = _extract_sent_file_from_message(message, "audio")
                    sent_entries.append((item, sent_file))

                processed_audio_items += len(chunk)

            except (TelegramError, TimedOut, NetworkError):
                logger.exception("send_audio media_group failed, fallback to one-by-one")

                for item_index, item in enumerate(chunk):
                    first_fallback_message = not sent_entries and item_index == 0
                    path = Path(item.path)
                    is_last_album_item = processed_audio_items + item_index == total_audio_items - 1

                    sent_file = await send_local_media(
                        settings=settings,
                        bot=context.bot,
                        chat_id=chat_id,
                        file_path=path,
                        media_type="audio",
                        caption=album_caption if is_last_album_item else "",
                        caption_entities=album_caption_entities if is_last_album_item else None,
                        title=item.title,
                        performer=item.author,
                        duration=item.duration,
                        width=item.width,
                        height=item.height,
                        reply_to_message_id=reply_to_message_id if first_fallback_message else None,
                    )

                    sent_entries.append((item, sent_file))
                    processed_audio_items += 1

        return sent_entries

    for item in audio_items:
        path = Path(item.path)

        sent_file = await send_local_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            file_path=path,
            media_type="audio",
            caption=caption or "🎵 Музыка из поста",
            caption_entities=caption_entities,
            title=item.title,
            performer=item.author,
            duration=item.duration,
            width=item.width,
            height=item.height,
            reply_to_message_id=None,
        )

        sent_entries.append((item, sent_file))

    return sent_entries


async def _send_single_items_and_collect(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    items: list,
    caption: str,
    caption_entities: list | None = None,
    platform: str,
    reply_to_message_id: int | None,
) -> list[tuple[DownloadedMedia, SentTelegramFile]]:
    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]] = []

    for index, item in enumerate(items):
        media_type = getattr(item, "media_type", None)
        path = Path(item.path)

        send_path = path
        send_media_type = media_type

        if media_type == "live_photo":
            # Пока кешируем live_photo как обычное video.
            # Настоящий sendLivePhoto через raw API не возвращает удобный file_id
            # в нашей текущей функции.
            send_media_type = "video"

        if send_media_type == "video" and platform == "instagram":
            send_path = _normalize_instagram_video_for_telegram(path)

        sent_file = await send_local_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            file_path=send_path,
            media_type=send_media_type,
            caption=caption,
            caption_entities=caption_entities,
            title=item.title,
            performer=item.author,
            duration=item.duration,
            width=item.width,
            height=item.height,
            reply_to_message_id=reply_to_message_id if index == 0 else None,
        )

        sent_entries.append((item, sent_file))

    return sent_entries

def _normalize_instagram_video_for_telegram(path: Path) -> Path:
    """
    Instagram stories/reels иногда приходят как mp4, который Telegram показывает
    как превью и не проигрывает нормально.

    Решение: пересобрать видео в обычный H.264 + AAC + faststart.
    """
    if not path.exists():
        return path

    if path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
        return path

    output_path = path.with_name(path.stem + "_telegram.mp4")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),

        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(
                "Instagram video normalized for Telegram | input=%s output=%s size_mb=%.2f",
                path,
                output_path,
                output_path.stat().st_size / 1024 / 1024,
            )
            return output_path

        logger.warning(
            "Instagram video normalization failed | file=%s | stderr=%s",
            path,
            result.stderr[-1500:],
        )
        return path

    except Exception:
        logger.exception("Instagram video normalization crashed | file=%s", path)
        return path

def _is_photo_video_album(items: list) -> bool:
    if len(items) < 2:
        return False

    return all(
        getattr(item, "media_type", None) in {"photo", "video"}
        for item in items
    )


def _chunk_items(items: list, chunk_size: int = 10) -> list[list]:
    return [
        items[i:i + chunk_size]
        for i in range(0, len(items), chunk_size)
    ]


async def _send_photo_video_album(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    items: list,
    caption: str | None = None,
    caption_entities: list | None = None,
    reply_to_message_id: int | None = None,
    settings=None,
    platform: str | None = None,
) -> list[tuple[DownloadedMedia, SentTelegramFile]] | None:
    """
    Отправляет фото/видео как Telegram album.
    Возвращает список (item, SentTelegramFile), чтобы потом сохранить file_id в кеш.

    Если альбом нельзя отправить безопасно, возвращает None.
    """
    if not _is_photo_video_album(items):
        return None

    chunks = _chunk_items(items, 10)

    # Важно: Telegram media_group требует минимум 2 элемента.
    # Если, например, 11 файлов, будет chunk 10 + chunk 1.
    # Чтобы не отправить часть альбома и потом не упасть, в таком случае
    # лучше fallback на отправку по одному.
    if any(len(chunk) < 2 for chunk in chunks):
        return None

    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]] = []

    try:
        for chunk_index, chunk in enumerate(chunks):
            with ExitStack() as stack:
                media_group = []

                for item_index, item in enumerate(chunk):
                    media_type = getattr(item, "media_type", None)
                    path = Path(item.path)

                    item_caption = caption if chunk_index == 0 and item_index == 0 else None
                    item_caption_entities = caption_entities if chunk_index == 0 and item_index == 0 else None

                    if media_type == "photo":
                        file_obj = stack.enter_context(open(path, "rb"))

                        media_group.append(
                            InputMediaPhoto(
                                media=file_obj,
                                caption=item_caption,
                                caption_entities=item_caption_entities,
                            )
                        )

                    elif media_type == "video":
                        send_path = path

                        if platform == "instagram":
                            send_path = _normalize_instagram_video_for_telegram(path)

                        file_obj = stack.enter_context(open(send_path, "rb"))

                        media_group.append(
                            InputMediaVideo(
                                media=file_obj,
                                caption=item_caption,
                                caption_entities=item_caption_entities,
                                supports_streaming=True,
                            )
                        )

                if len(media_group) < 2:
                    return None

                messages = await context.bot.send_media_group(
                    chat_id=chat_id,
                    media=media_group,
                    reply_to_message_id=reply_to_message_id if chunk_index == 0 else None,
                    read_timeout=getattr(settings, "send_read_timeout", None),
                    write_timeout=getattr(settings, "send_write_timeout", None),
                    connect_timeout=getattr(settings, "send_connect_timeout", None),
                    pool_timeout=getattr(settings, "send_pool_timeout", None),
                )

                for item, message in zip(chunk, messages):
                    media_type = getattr(item, "media_type", None)
                    sent_file = _extract_sent_file_from_message(message, media_type)
                    sent_entries.append((item, sent_file))

        return sent_entries

    except (TelegramError, TimedOut, NetworkError):
        logger.exception("send_media_group failed, fallback to one-by-one")
        return None

    except Exception:
        logger.exception("Unexpected send_media_group error, fallback to one-by-one")
        return None

def _get_download_semaphore(context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> asyncio.Semaphore:
    semaphore = context.application.bot_data.get("download_semaphore")

    if semaphore is None:
        semaphore = asyncio.Semaphore(settings.worker_count)
        context.application.bot_data["download_semaphore"] = semaphore

    return semaphore


async def _send_cached_bundle(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    request_id: int,
    user_id: int,
    rows,
    title: str,
    platform: str,
    quality: int | None,
    audio_label: str | None,
    reply_to_message_id: int | None,
) -> int:
    sent_count = 0
    item_total = len(rows)

    for index, row in enumerate(rows):
        caption = build_media_caption(
            title=row["title"] or title,
            platform=platform,
            bot_username=settings.bot_username_text,
            quality=quality,
            audio_label=audio_label,
            item_index=index,
            item_total=item_total,
        )

        await send_cached_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            tg_file_id=row["tg_file_id"],
            send_type=row["tg_send_type"],
            caption=caption,
            reply_to_message_id=reply_to_message_id if index == 0 else None,
        )

        add_download_item(
            settings,
            request_id=request_id,
            cache_key=row["cache_key"],
            item_index=index,
            media_type=row["media_type"],
            status="sent",
            cache_status="hit",
            tg_file_id=row["tg_file_id"],
            tg_send_type=row["tg_send_type"],
            file_size=row["file_size"],
            width=row["width"],
            height=row["height"],
            duration=row["duration"],
        )

        sent_count += 1

    if rows:
        touch_cache_bundle(settings, rows[0]["bundle_key"])

    increment_user_cache_hit(settings, user_id)

    return sent_count


async def _send_and_cache_downloaded_items(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    request_id: int,
    route: RouteDecision,
    original_url: str,
    resolved_url: str | None,
    source_key: str,
    variant_key: str,
    bundle_key: str,
    items: list[DownloadedMedia],
    title: str,
    quality: int | None,
    audio_lang: str | None,
    audio_label: str | None,
    reply_to_message_id: int | None,
) -> int:
    sent_count = 0
    item_total = len(items)

    for index, item in enumerate(items):
        cache_key = build_cache_key(bundle_key, index)

        caption = build_media_caption(
            title=item.title or title,
            platform=route.platform.value,
            bot_username=settings.bot_username_text,
            quality=quality,
            audio_label=audio_label,
            item_index=index,
            item_total=item_total,
        )

        sent_file = await send_local_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            file_path=item.path,
            media_type=item.media_type,
            caption=caption,
            title=item.title or title,
            performer=item.author,
            duration=item.duration,
            width=item.width,
            height=item.height,
            reply_to_message_id=reply_to_message_id if index == 0 else None,
        )

        save_cached_item(
            settings,
            cache_key=cache_key,
            bundle_key=bundle_key,
            source_key=source_key,
            variant_key=variant_key,
            platform=route.platform.value,
            content_type=route.content_type.value,
            media_type=item.media_type,
            original_url=original_url,
            resolved_url=resolved_url,
            title=item.title or title,
            author=item.author,
            item_index=index,
            item_total=item_total,
            tg_file_id=sent_file.file_id,
            tg_file_unique_id=sent_file.file_unique_id,
            tg_send_type=sent_file.send_type,
            file_size=item.file_size,
            width=item.width,
            height=item.height,
            duration=item.duration,
            quality=quality,
            audio_lang=audio_lang,
            album_title=getattr(item, "album_title", None),
        )

        add_download_item(
            settings,
            request_id=request_id,
            cache_key=cache_key,
            item_index=index,
            media_type=item.media_type,
            status="sent",
            cache_status="miss",
            tg_file_id=sent_file.file_id,
            tg_send_type=sent_file.send_type,
            file_size=item.file_size,
            width=item.width,
            height=item.height,
            duration=item.duration,
        )

        sent_count += 1

    return sent_count

LIVE_PHOTO_MAX_SECONDS = 10.0
LIVE_PHOTO_MAX_BYTES = 10 * 1024 * 1024


def _probe_live_video(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size",
        "-of",
        "default=noprint_wrappers=1:nokey=0",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {}

        info = {}

        for line in (result.stdout or "").splitlines():
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()

        try:
            duration = float(info.get("duration") or 0)
        except Exception:
            duration = 0.0

        try:
            size = int(info.get("size") or path.stat().st_size)
        except Exception:
            size = path.stat().st_size

        return {
            "duration": duration,
            "size": size,
        }

    except Exception:
        logger.exception("Live photo ffprobe failed | file=%s", path)
        return {}


def _make_live_photo_cover(video_path: Path) -> Path | None:
    cover_path = video_path.with_name(video_path.stem + "_live_cover.jpg")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(cover_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )

        if result.returncode == 0 and cover_path.exists() and cover_path.stat().st_size > 0:
            return cover_path

        logger.warning(
            "Live photo cover creation failed | file=%s | stderr=%s",
            video_path,
            result.stderr[-1000:],
        )
        return None

    except Exception:
        logger.exception("Live photo cover creation crashed | file=%s", video_path)
        return None

def _get_bot_api_method_url(settings, method: str) -> str:
    token = getattr(settings, "bot_token", None) or getattr(settings, "BOT_TOKEN", None)

    if not token:
        raise RuntimeError("BOT_TOKEN not found in settings")

    use_local = bool(getattr(settings, "use_local_bot_api", False))
    base_url = getattr(settings, "bot_api_base_url", None) or "https://api.telegram.org"

    if use_local:
        return f"{str(base_url).rstrip('/')}/bot{token}/{method}"

    return f"https://api.telegram.org/bot{token}/{method}"


async def _raw_send_live_photo(
    *,
    settings,
    chat_id: int,
    live_photo_path: Path,
    photo_path: Path,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
) -> bool:
    url = _get_bot_api_method_url(settings, "sendLivePhoto")

    data = {
        "chat_id": str(chat_id),
    }

    if caption:
        data["caption"] = caption[:1024]

    if reply_to_message_id:
        data["reply_parameters"] = json.dumps(
            {
                "message_id": reply_to_message_id,
            },
            ensure_ascii=False,
        )

    timeout = httpx.Timeout(
        connect=getattr(settings, "send_connect_timeout", 30) or 30,
        read=getattr(settings, "send_read_timeout", 600) or 600,
        write=getattr(settings, "send_write_timeout", 1800) or 1800,
        pool=getattr(settings, "send_pool_timeout", 30) or 30,
    )

    try:
        with open(live_photo_path, "rb") as live_file, open(photo_path, "rb") as photo_file:
            files = {
                "live_photo": (
                    live_photo_path.name,
                    live_file,
                    "video/mp4",
                ),
                "photo": (
                    photo_path.name,
                    photo_file,
                    "image/jpeg",
                ),
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    data=data,
                    files=files,
                )

        if response.status_code != 200:
            logger.warning(
                "Raw sendLivePhoto HTTP failed | status=%s body=%s",
                response.status_code,
                response.text[-1500:],
            )
            return False

        payload = response.json()

        if not payload.get("ok"):
            logger.warning(
                "Raw sendLivePhoto Telegram failed | payload=%s",
                payload,
            )
            return False

        logger.info(
            "Raw sendLivePhoto OK | chat_id=%s live_photo=%s photo=%s",
            chat_id,
            live_photo_path,
            photo_path,
        )
        return True

    except Exception:
        logger.exception(
            "Raw sendLivePhoto crashed | live_photo=%s photo=%s",
            live_photo_path,
            photo_path,
        )
        return False

async def _send_live_photo_from_video(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_path: Path,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    settings=None,
) -> bool:
    if settings is None:
        settings = context.application.bot_data["settings"]

    probe = _probe_live_video(video_path)
    duration = float(probe.get("duration") or 0)
    size = int(probe.get("size") or video_path.stat().st_size)

    if duration <= 0:
        logger.warning("Live photo rejected: unknown duration | file=%s", video_path)
        return False

    if duration > LIVE_PHOTO_MAX_SECONDS:
        logger.info(
            "Live photo rejected: duration too long | file=%s duration=%.2f",
            video_path,
            duration,
        )
        return False

    if size > LIVE_PHOTO_MAX_BYTES:
        logger.info(
            "Live photo rejected: file too big | file=%s size_mb=%.2f",
            video_path,
            size / 1024 / 1024,
        )
        return False

    cover_path = _make_live_photo_cover(video_path)

    if not cover_path:
        return False

    sent = await _raw_send_live_photo(
        settings=settings,
        chat_id=chat_id,
        live_photo_path=video_path,
        photo_path=cover_path,
        caption=caption,
        reply_to_message_id=reply_to_message_id,
    )

    if sent:
        logger.info(
            "Live photo sent via raw Bot API | chat_id=%s file=%s duration=%.2f size_mb=%.2f",
            chat_id,
            video_path,
            duration,
            size / 1024 / 1024,
        )
        return True

    return False

AUDIO_MEDIA_TYPES = {"audio"}
VISUAL_MEDIA_TYPES = {"photo", "video", "live_photo"}


def _split_visual_and_audio_items(items: list) -> tuple[list, list]:
    visual_items = []
    audio_items = []

    for item in items:
        media_type = getattr(item, "media_type", None)

        if media_type in AUDIO_MEDIA_TYPES:
            audio_items.append(item)
        else:
            visual_items.append(item)

    return visual_items, audio_items


def _extract_audio_from_video(video_path: Path) -> Path | None:
    output_path = video_path.with_name(video_path.stem + "_audio.mp3")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-map",
        "0:a:0",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,
        )

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(
                "Audio extracted from video | video=%s audio=%s size_mb=%.2f",
                video_path,
                output_path,
                output_path.stat().st_size / 1024 / 1024,
            )
            return output_path

        logger.warning(
            "Audio extract failed | video=%s | returncode=%s | stderr=%s",
            video_path,
            result.returncode,
            result.stderr[-1000:],
        )
        return None

    except Exception:
        logger.exception("Audio extract crashed | video=%s", video_path)
        return None


async def _send_audio_file(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    path: Path,
    caption: str | None = None,
    caption_entities: list | None = None,
    reply_to_message_id: int | None = None,
    settings=None,
) -> None:
    try:
        with open(path, "rb") as f:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                caption=caption,
                caption_entities=caption_entities,
                reply_to_message_id=reply_to_message_id,
                title=path.stem[:64],
                performer="TikTok / Reels",
                read_timeout=getattr(settings, "send_read_timeout", None),
                write_timeout=getattr(settings, "send_write_timeout", None),
                connect_timeout=getattr(settings, "send_connect_timeout", None),
                pool_timeout=getattr(settings, "send_pool_timeout", None),
            )

    except Exception:
        logger.exception("send_audio failed, fallback to document | file=%s", path)

        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=caption,
                caption_entities=caption_entities,
                reply_to_message_id=reply_to_message_id,
                read_timeout=getattr(settings, "send_read_timeout", None),
                write_timeout=getattr(settings, "send_write_timeout", None),
                connect_timeout=getattr(settings, "send_connect_timeout", None),
                pool_timeout=getattr(settings, "send_pool_timeout", None),
            )


async def _send_audio_items(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    audio_items: list,
    caption: str | None = None,
    caption_entities: list | None = None,
    settings=None,
) -> None:
    for item in audio_items:
        path = Path(item.path)

        await _send_audio_file(
            context=context,
            chat_id=chat_id,
            path=path,
            caption=caption,
            caption_entities=caption_entities,
            reply_to_message_id=None,
            settings=settings,
        )


async def _send_extracted_audio_for_videos(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    visual_items: list,
    platform: str,
    source_url: str | None = None,
    settings=None,
) -> None:
    # Пока отдельно извлекаем звук только для TikTok и Instagram/Reels.
    if platform not in {"tiktok", "instagram"}:
        return

    if settings is None:
        settings = context.application.bot_data["settings"]

    for item in visual_items:
        if getattr(item, "media_type", None) != "video":
            continue

        video_path = Path(item.path)
        audio_path = _extract_audio_from_video(video_path)

        if not audio_path:
            continue

        caption_payload = _content_caption(
            settings=settings,
            title=getattr(item, "title", None) or "Музыка из видео",
            platform=platform,
            source_url=source_url,
            media_type="audio",
        )

        await _send_audio_file(
            context=context,
            chat_id=chat_id,
            path=audio_path,
            caption=caption_payload.text,
            caption_entities=caption_payload.entities,
            reply_to_message_id=None,
            settings=settings,
        )

async def _extract_send_audio_from_videos_and_collect(
    *,
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    visual_items: list,
    platform: str,
    source_url: str | None = None,
) -> list[tuple[DownloadedMedia, SentTelegramFile]]:
    sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]] = []

    if platform not in {"tiktok", "instagram"}:
        return sent_entries

    for item in visual_items:
        if getattr(item, "media_type", None) != "video":
            continue

        video_path = Path(item.path)
        audio_path = _extract_audio_from_video(video_path)

        if not audio_path:
            continue

        audio_item = DownloadedMedia(
            path=audio_path,
            media_type="audio",
            item_index=0,
            item_total=1,
            title=(item.title or "Audio"),
            author=item.author,
            duration=item.duration,
            file_size=audio_path.stat().st_size,
        )

        caption_payload = _content_caption(
            settings=settings,
            title=audio_item.title or "Музыка из видео",
            platform=platform,
            source_url=source_url,
            media_type="audio",
        )

        sent_file = await send_local_media(
            settings=settings,
            bot=context.bot,
            chat_id=chat_id,
            file_path=audio_path,
            media_type="audio",
            caption=caption_payload.text,
            caption_entities=caption_payload.entities,
            title=audio_item.title,
            performer=audio_item.author,
            duration=audio_item.duration,
            reply_to_message_id=None,
        )

        sent_entries.append((audio_item, sent_file))

    return sent_entries

async def process_download_request(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user,
    language_code: str,
    original_url: str,
    resolved_url: str | None,
    route,
    reply_to_message_id: int | None = None,
    quality: int | None = None,
    audio_lang: str | None = None,
    audio_label: str | None = None,
    audio_format_id: str | None = None,
) -> None:
    settings = context.application.bot_data["settings"]

    wait_message = None

    platform = getattr(route.platform, "value", str(route.platform))
    content_type = getattr(route.content_type, "value", str(route.content_type))
    action = getattr(route.action, "value", str(route.action))

    title = getattr(route, "title", None) or "Media"
    user_id = getattr(user, "id", None)
    request_id = None

    if await send_access_denied_if_needed(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        reply_to_message_id=reply_to_message_id,
    ):
        logger.info(
            "Download request blocked by access control | user_id=%s url=%s",
            user_id,
            original_url,
        )
        return

    source_key = build_source_key(route.platform, original_url, resolved_url)
    album_item_limit = _album_track_limit(
        settings=settings,
        user_id=user_id,
        route=route,
        original_url=original_url,
        resolved_url=resolved_url,
    )
    variant_key = build_variant_key(
        action=route.action,
        quality=quality,
        audio_lang=audio_lang,
        media_type=_album_limit_variant(album_item_limit),
    )
    bundle_key = build_bundle_key(source_key, variant_key)

    cache_allowed = _is_cache_allowed(
        route=route,
        original_url=original_url,
        resolved_url=resolved_url,
    )

    logger.info(
        "Download request started | user_id=%s chat_id=%s platform=%s content_type=%s action=%s url=%s resolved=%s quality=%s audio=%s audio_format_id=%s cache_allowed=%s bundle_key=%s",
        user_id,
        chat_id,
        platform,
        content_type,
        action,
        original_url,
        resolved_url,
        quality,
        audio_lang,
        audio_format_id,
        cache_allowed,
        bundle_key,
    )

    if user_id:
        try:
            increment_user_request(settings, user_id)
            request_id = create_download_request(
                settings,
                user_id=user_id,
                username=getattr(user, "username", None),
                full_name=get_full_name(user),
                language_code=language_code,
                original_url=original_url,
                resolved_url=resolved_url,
                platform=platform,
                content_type=content_type,
                action=action,
                source_key=source_key,
                variant_key=variant_key,
                bundle_key=bundle_key,
                title=title,
                requested_quality=quality,
                requested_audio_lang=audio_lang,
                status="started",
            )
        except Exception:
            logger.exception("Could not create download request row | user_id=%s url=%s", user_id, original_url)

    # ============================================================
    # 1. Cache hit: если уже есть tg_file_id, ничего не скачиваем.
    # ============================================================
    if cache_allowed:
        try:
            cached_rows = _get_complete_cached_rows(
                get_cached_bundle(settings, bundle_key)
            )

            if cached_rows and _is_stale_youtube_music_album_cache(cached_rows, platform):
                logger.info(
                    "Media cache STALE | user_id=%s bundle_key=%s reason=%s",
                    user_id,
                    bundle_key,
                    "youtube_music_album_duplicate_titles",
                )
                cached_rows = []

            if cached_rows:
                logger.info(
                    "Media cache HIT | user_id=%s bundle_key=%s items=%s",
                    user_id,
                    bundle_key,
                    len(cached_rows),
                )

                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action="upload_document")
                except Exception:
                    pass

                sent_count = await _send_cached_bundle_fast(
                    settings=settings,
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                    rows=cached_rows,
                    title=title,
                    platform=platform,
                    quality=quality,
                    audio_label=audio_label,
                    audio_lang=audio_lang,
                    source_url=original_url or resolved_url,
                    reply_to_message_id=reply_to_message_id,
                )

                if user_id:
                    increment_user_download(settings, user_id)

                if request_id:
                    try:
                        for index, row in enumerate(cached_rows):
                            add_download_item(
                                settings,
                                request_id=request_id,
                                cache_key=row["cache_key"],
                                item_index=index,
                                media_type=row["media_type"],
                                status="sent",
                                cache_status="hit",
                                tg_file_id=row["tg_file_id"],
                                tg_send_type=row["tg_send_type"],
                                file_size=row["file_size"],
                                width=row["width"],
                                height=row["height"],
                                duration=row["duration"],
                            )

                        update_download_request(
                            settings,
                            request_id,
                            status="sent",
                            cache_status="hit",
                            items_total=len(cached_rows),
                            items_sent=sent_count,
                        )
                    except Exception:
                        logger.exception("Could not write cache-hit download request items | request_id=%s", request_id)

                await maybe_send_after_download_ad(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                )

                await _maybe_send_spotify_savers_promo(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                    original_url=original_url,
                    resolved_url=resolved_url,
                    has_youtube_music_audio=_rows_include_youtube_music_audio(cached_rows, original_url, resolved_url),
                )

                return

            logger.info(
                "Media cache MISS | user_id=%s bundle_key=%s",
                user_id,
                bundle_key,
            )

        except Exception:
            logger.exception(
                "Media cache check failed, continue without cache | user_id=%s bundle_key=%s",
                user_id,
                bundle_key,
            )

    # ============================================================
    # 2. Cache miss: скачиваем как обычно.
    # ============================================================
    try:
        processing = processing_message(
            platform,
            content_type=getattr(route.content_type, "value", str(route.content_type)),
            url=resolved_url or original_url,
            language_code=language_code,
        )
        wait_message = await context.bot.send_message(
            chat_id=chat_id,
            text=processing.text,
            entities=processing.entities,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
        )
    except Exception:
        wait_message = None

    try:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_document")
        except Exception:
            pass

        temp_root = settings.base_dir / "media" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=temp_root) as tmpdir:
            download_url = resolved_url or original_url

            def _download_operation(slot: int):
                proxy_result = run_with_proxy_rotation_sync(
                    settings=settings,
                    platform=platform,
                    operation=lambda proxy_url: download_media_bundle(
                        settings=settings,
                        url=download_url,
                        route=route,
                        output_dir=Path(tmpdir),
                        quality=quality,
                        audio_lang=audio_lang,
                        audio_format_id=audio_format_id,
                        platform_auth_slot=slot,
                        playlist_item_limit=album_item_limit,
                        proxy_url=proxy_url,
                    ),
                    operation_name="download_media_bundle",
                )
                return proxy_result.value

            auth_result = await run_with_cookie_rotation(
                context=context,
                url=download_url,
                operation=_download_operation,
                platform=platform,
                operation_name="download_media_bundle",
            )
            items = auth_result.value

            if not items:
                raise RuntimeError("download completed but no media items were returned")

            if album_item_limit and len(items) > album_item_limit:
                logger.info(
                    "Audio playlist limited for free user | user_id=%s limit=%s original_items=%s",
                    user_id,
                    album_item_limit,
                    len(items),
                )
                items = items[:album_item_limit]

            visual_items, audio_items = _split_visual_and_audio_items(items)

            logger.info(
                "Download request files ready | user_id=%s count=%s types=%s",
                user_id,
                len(items),
                [getattr(item, "media_type", None) for item in items],
            )

            bot_username = getattr(settings, "bot_username_text", None) or "@Top_Savers_bot"

            first_visual = visual_items[0] if visual_items else None
            first_audio = audio_items[0] if audio_items else None
            caption_media_type = getattr(first_visual or first_audio, "media_type", None)
            caption_title = _caption_title_for_media(
                platform=platform,
                media_type=caption_media_type,
                route_title=title,
                item_title=getattr(first_visual or first_audio, "title", None),
            )
            caption_payload = _content_caption(
                settings=settings,
                title=caption_title,
                platform=platform,
                source_url=original_url or resolved_url,
                media_type=caption_media_type,
                quality=quality,
                audio_label=audio_label,
                audio_lang=audio_lang,
                item_index=0,
                item_total=max(1, len(visual_items) or len(audio_items)),
            )

            sent_entries: list[tuple[DownloadedMedia, SentTelegramFile]] = []

            # ============================================================
            # 3. Пробуем отправить визуальные элементы альбомом.
            # ============================================================
            album_entries = await _send_photo_video_album(
                context=context,
                chat_id=chat_id,
                items=visual_items,
                caption=caption_payload.text,
                caption_entities=caption_payload.entities,
                reply_to_message_id=reply_to_message_id,
                settings=settings,
                platform=platform,
            )

            if album_entries:
                logger.info(
                    "Download request sent as album | user_id=%s chat_id=%s count=%s",
                    user_id,
                    chat_id,
                    len(album_entries),
                )

                sent_entries.extend(album_entries)

            else:
                # ========================================================
                # 4. Если альбом нельзя, отправляем по одному.
                # ========================================================
                single_entries = await _send_single_items_and_collect(
                    settings=settings,
                    context=context,
                    chat_id=chat_id,
                    items=visual_items,
                    caption=caption_payload.text,
                    caption_entities=caption_payload.entities,
                    platform=platform,
                    reply_to_message_id=reply_to_message_id,
                )

                sent_entries.extend(single_entries)

            # ============================================================
            # 5. Отдельные аудио-файлы, которые реально скачались.
            # Например музыка из TikTok photo post.
            # ============================================================
            audio_album_mode = platform == "youtube" and len(audio_items) >= 2
            audio_album_title = (
                _album_title_from_audio_items(audio_items, title)
                if audio_album_mode
                else title
            )
            audio_caption_payload = _content_caption(
                settings=settings,
                title=audio_album_title,
                platform=platform,
                source_url=original_url or resolved_url,
                media_type="audio",
                item_index=0,
                item_total=max(1, len(audio_items)),
            )

            audio_entries = await _send_audio_items_and_collect(
                settings=settings,
                context=context,
                chat_id=chat_id,
                audio_items=audio_items,
                caption=audio_caption_payload.text,
                caption_entities=audio_caption_payload.entities,
                reply_to_message_id=reply_to_message_id if not sent_entries else None,
                group_as_album=audio_album_mode,
            )

            sent_entries.extend(audio_entries)

            extracted_audio_entries = await _extract_send_audio_from_videos_and_collect(
                settings=settings,
                context=context,
                chat_id=chat_id,
                visual_items=visual_items,
                platform=platform,
                source_url=original_url or resolved_url,
            )
            sent_entries.extend(extracted_audio_entries)

            if sent_entries:
                count_cookie_success(
                    settings,
                    auth_result.platform or platform,
                    auth_result.slot,
                )

                if user_id:
                    increment_user_download(settings, user_id)

            # ============================================================
            # 6. Сохраняем file_id в кеш.
            # ============================================================
            if cache_allowed and sent_entries:
                try:
                    _save_sent_entries_to_cache(
                        settings=settings,
                        route=route,
                        original_url=original_url,
                        resolved_url=resolved_url,
                        source_key=source_key,
                        variant_key=variant_key,
                        bundle_key=bundle_key,
                        sent_entries=sent_entries,
                        title=title,
                        quality=quality,
                        audio_lang=audio_lang,
                    )

                    logger.info(
                        "Media cache SAVED | user_id=%s bundle_key=%s items=%s",
                        user_id,
                        bundle_key,
                        len(sent_entries),
                    )

                except Exception:
                    logger.exception(
                        "Media cache save failed | user_id=%s bundle_key=%s",
                        user_id,
                        bundle_key,
                    )

            if wait_message:
                try:
                    await context.bot.delete_message(
                        chat_id=chat_id,
                        message_id=wait_message.message_id,
                    )
                except Exception:
                    pass

            if sent_entries:
                if request_id:
                    try:
                        for index, (item, sent_file) in enumerate(sent_entries):
                            add_download_item(
                                settings,
                                request_id=request_id,
                                cache_key=build_cache_key(bundle_key, index),
                                item_index=index,
                                media_type=item.media_type,
                                status="sent",
                                cache_status="miss",
                                tg_file_id=sent_file.file_id,
                                tg_send_type=sent_file.send_type,
                                file_size=item.file_size,
                                width=item.width,
                                height=item.height,
                                duration=item.duration,
                            )

                        update_download_request(
                            settings,
                            request_id,
                            status="sent",
                            cache_status="miss",
                            items_total=len(items),
                            items_sent=len(sent_entries),
                        )
                    except Exception:
                        logger.exception("Could not write fresh download request items | request_id=%s", request_id)

                await maybe_send_after_download_ad(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                )

                await _maybe_send_spotify_savers_promo(
                    context=context,
                    chat_id=chat_id,
                    user_id=user_id,
                    original_url=original_url,
                    resolved_url=resolved_url,
                    has_youtube_music_audio=_sent_entries_include_youtube_music_audio(
                        sent_entries,
                        original_url,
                        resolved_url,
                    ),
                )

            logger.info(
                "Download request finished | user_id=%s chat_id=%s count=%s cached_items=%s",
                user_id,
                chat_id,
                len(items),
                len(sent_entries),
            )

    except Exception as e:
        logger.exception(
            "Download request failed | user_id=%s url=%s",
            user_id,
            original_url,
        )

        if wait_message:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=wait_message.message_id,
                )
            except Exception:
                pass

        if request_id:
            try:
                update_download_request(
                    settings,
                    request_id,
                    status="failed",
                    cache_status="miss",
                    error_type=type(e).__name__,
                    error_text=str(e)[:1000],
                )
            except Exception:
                logger.exception("Could not update failed download request | request_id=%s", request_id)

        try:
            public_error = public_download_error_message(e, platform, language_code=language_code)
            await context.bot.send_message(
                chat_id=chat_id,
                text=public_error.text,
                entities=public_error.entities,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception:
            pass
