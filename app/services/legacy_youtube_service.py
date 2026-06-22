import asyncio
import hashlib
import logging
import tempfile
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import ContextTypes

from app.config import Settings
from app.downloader.legacy_youtube_downloader import (
    download_video_smart_legacy,
    fetch_video_metadata_legacy,
    format_duration_legacy,
    format_quality_label_legacy,
    get_audio_caption_label,
    get_audio_missing_text,
    get_available_youtube_audio_langs,
    SUPPORTED_YOUTUBE_AUDIO_LANGS,
    YOUTUBE_AUDIO_LABELS,
    normalize_audio_lang,
)

from urllib.parse import urlparse

from app.db.cache_repo import get_cached_bundle, save_cached_item, touch_cache_bundle
from app.db.downloads_repo import add_download_item, create_download_request, update_download_request
from app.db.users_repo import increment_user_cache_hit, increment_user_download, increment_user_request
from app.downloader.cache_keys import build_bundle_key, build_cache_key, build_source_key, build_variant_key
from app.downloader.content_types import DownloadAction, Platform
from app.services.access_control_service import send_access_denied_if_needed
from app.services.ads_service import maybe_send_after_download_ad
from app.services.cookie_auth_service import count_cookie_success, run_with_cookie_rotation
from app.services.proxy_rotation_service import run_with_proxy_rotation_sync
from app.telegram_ui.captions import CaptionPayload, build_content_caption, build_custom_emoji_lines
from app.telegram_ui.sender import send_cached_media, send_local_media
from app.telegram_ui.user_messages import processing_message, public_download_error_message
from app.texts.emojis import CUSTOM_EMOJIS
from app.texts.keys import TextKey
from app.texts.renderer import render_text

logger = logging.getLogger(__name__)


LEGACY_YOUTUBE_QUALITY_PREFIX = "lyq:"
LEGACY_YOUTUBE_AUDIO_PREFIX = "lya:"
LEGACY_YOUTUBE_BACK_PREFIX = "lyb:"

def is_youtube_shorts_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").lower()
        return "/shorts/" in path
    except Exception:
        return False

def build_audio_lang_order(
    available_audio_langs: set[str],
    user_language_code: str | None,
) -> list[str]:
    available = {
        normalize_audio_lang(lang)
        for lang in available_audio_langs
        if normalize_audio_lang(lang) in SUPPORTED_YOUTUBE_AUDIO_LANGS
    }

    user_lang = normalize_audio_lang(user_language_code)

    priority: list[str] = []

    if user_lang in SUPPORTED_YOUTUBE_AUDIO_LANGS:
        priority.append(user_lang)

    for lang in ("ru", "en", "es", "ar", "zh", "th"):
        if lang not in priority:
            priority.append(lang)

    result: list[str] = []

    for lang in priority:
        if lang in available and lang not in result:
            result.append(lang)

    return result[:6]


def chunk_langs(langs: list[str], size: int = 3) -> list[list[str]]:
    return [
        langs[i:i + size]
        for i in range(0, len(langs), size)
    ]


def _youtube_preview_payload(
    *,
    title: str,
    duration: str | None = None,
    is_shorts: bool = False,
    lines: list[tuple[str, str]] | None = None,
) -> CaptionPayload:
    emoji_key = "youtube_shorts" if is_shorts else "youtube"
    payload_lines: list[tuple[str, str]] = [(emoji_key, title or "YouTube видео")]

    if duration:
        payload_lines.append(("info", f"Длительность: {duration}"))

    payload_lines.extend(lines or [])

    return build_custom_emoji_lines(payload_lines)


def build_legacy_youtube_quality_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "720p",
                callback_data=f"{LEGACY_YOUTUBE_QUALITY_PREFIX}{token}:720",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
            InlineKeyboardButton(
                "1080p",
                callback_data=f"{LEGACY_YOUTUBE_QUALITY_PREFIX}{token}:1080",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
        ],
        [
            InlineKeyboardButton(
                "1080p HQ",
                callback_data=f"{LEGACY_YOUTUBE_QUALITY_PREFIX}{token}:1081",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
        ],
    ])


def build_legacy_youtube_audio_keyboard(
    token: str,
    quality: int,
    available_audio_langs: set[str],
    user_language_code: str | None = None,
    show_back_button: bool = True,
) -> InlineKeyboardMarkup:
    keyboard = []

    ordered_langs = build_audio_lang_order(
        available_audio_langs=available_audio_langs,
        user_language_code=user_language_code,
    )

    for row_langs in chunk_langs(ordered_langs, 3):
        keyboard.append([
            InlineKeyboardButton(
                YOUTUBE_AUDIO_LABELS.get(lang, lang.upper()),
                callback_data=f"{LEGACY_YOUTUBE_AUDIO_PREFIX}{token}:{quality}:{lang}",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get(f"lang_{lang}") or None,
            )
            for lang in row_langs
        ])

    keyboard.append([
        InlineKeyboardButton(
            "Original",
            callback_data=f"{LEGACY_YOUTUBE_AUDIO_PREFIX}{token}:{quality}:auto",
            icon_custom_emoji_id=CUSTOM_EMOJIS.get("music") or None,
        )
    ])

    if show_back_button:
        keyboard.append([
            InlineKeyboardButton(
                "⬅️ Назад к качеству",
                callback_data=f"{LEGACY_YOUTUBE_BACK_PREFIX}{token}",
            )
        ])

    return InlineKeyboardMarkup(keyboard)


async def start_legacy_youtube_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    language_code: str | None = None,
) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    if await send_access_denied_if_needed(
        context=context,
        chat_id=update.effective_chat.id,
        user_id=user.id if user else None,
        reply_to_message_id=update.message.message_id,
    ):
        logger.info(
            "Legacy YouTube flow blocked by access control | user_id=%s url=%s",
            user.id if user else None,
            url,
        )
        return

    try:
        auth_result = await run_with_cookie_rotation(
            context=context,
            url=url,
            platform="youtube",
            operation=lambda slot: run_with_proxy_rotation_sync(
                settings=settings,
                platform="youtube",
                operation=lambda proxy_url: fetch_video_metadata_legacy(
                    settings,
                    url,
                    platform_auth_slot=slot,
                    proxy_url=proxy_url,
                ),
                operation_name="legacy_youtube_metadata",
            ).value,
            operation_name="legacy_youtube_metadata",
        )
        info = auth_result.value
    except Exception as e:
        logger.exception("Legacy YouTube metadata failed | url=%s", url)
        public_error = public_download_error_message(e, "youtube", language_code=language_code)

        await update.message.reply_text(
            public_error.text,
            entities=public_error.entities,
            reply_to_message_id=update.message.message_id,
        )
        return

    token = hashlib.sha1(f"{user.id}:{url}:{time.time()}".encode("utf-8")).hexdigest()[:16]
    available_audio_langs = get_available_youtube_audio_langs(info)
    is_shorts = is_youtube_shorts_url(url)

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    pending_choices[token] = {
        "type": "legacy_youtube",
        "url": url,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
        "language_code": language_code,
        "title": info.get("title") or "YouTube видео",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "available_audio_langs": list(available_audio_langs),
        "is_shorts": is_shorts,
        "created_at": time.time(),
    }

    logger.info(
        "Legacy YouTube flow prepared | user_id=%s url=%s title=%s shorts=%s langs=%s",
        user.id,
        url,
        info.get("title"),
        is_shorts,
        sorted(available_audio_langs),
    )

    title = info.get("title") or "YouTube видео"
    duration = format_duration_legacy(info.get("duration"))

    # ============================================================
    # YouTube Shorts:
    # без выбора качества, сразу озвучка, качество = 1080p HQ
    # ============================================================
    if is_shorts:
        quality = 1081

        # Если вообще нет RU/EN/ES/AR/ZH/TH, сразу качаем Original.
        if not available_audio_langs:
            text, entities = render_text(
                TextKey.YOUTUBE_SHORTS_AUDIO_AUTO_SELECTED,
                language_code=language_code,
            )
            await update.message.reply_text(
                text,
                entities=entities,
                reply_to_message_id=update.message.message_id,
                disable_web_page_preview=True,
            )

            await process_legacy_youtube_download(
                context=context,
                chat_id=update.effective_chat.id,
                reply_to_message_id=update.message.message_id,
                url=url,
                title=title,
                requested_quality=quality,
                requested_audio_lang="auto",
                user_id=user.id,
                language_code=language_code,
            )
            return

        text, entities = render_text(
            TextKey.YOUTUBE_SHORTS_CHOOSE_AUDIO,
            language_code=language_code,
            title=title,
            duration=duration,
        )

        await update.message.reply_text(
            text,
            entities=entities,
            reply_markup=build_legacy_youtube_audio_keyboard(
                token=token,
                quality=quality,
                available_audio_langs=available_audio_langs,
                user_language_code=language_code,
                show_back_button=False,
            ),
            reply_to_message_id=update.message.message_id,
            disable_web_page_preview=True,
        )
        return

    # ============================================================
    # Обычный YouTube:
    # сначала выбор качества, потом выбор озвучки
    # ============================================================
    text, entities = render_text(
        TextKey.YOUTUBE_CHOOSE_QUALITY,
        language_code=language_code,
        title=title,
        duration=duration,
    )

    await update.message.reply_text(
        text,
        entities=entities,
        reply_markup=build_legacy_youtube_quality_keyboard(token),
        reply_to_message_id=update.message.message_id,
        disable_web_page_preview=True,
    )


async def legacy_youtube_quality_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(LEGACY_YOUTUBE_QUALITY_PREFIX):
        return

    try:
        payload = data.replace(LEGACY_YOUTUBE_QUALITY_PREFIX, "", 1)
        token, quality_raw = payload.split(":", 1)
        quality = int(quality_raw)
    except Exception:
        text, _ = render_text(TextKey.CALLBACK_INVALID_CHOICE)
        await query.answer(text, show_alert=True)
        return

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        text, _ = render_text(TextKey.CALLBACK_CHOICE_EXPIRED)
        await query.answer(text, show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        text, _ = render_text(TextKey.CALLBACK_NOT_FOR_YOU, language_code=choice.get("language_code"))
        await query.answer(text, show_alert=True)
        return

    await query.answer()

    available_audio_langs = set(choice.get("available_audio_langs") or [])
    title = choice.get("title") or "YouTube видео"

    logger.info(
        "Legacy YouTube quality selected | user_id=%s token=%s quality=%s langs=%s",
        user.id if user else None,
        token,
        quality,
        sorted(available_audio_langs),
    )

    text, entities = render_text(
        TextKey.YOUTUBE_CHOOSE_AUDIO,
        language_code=choice.get("language_code"),
        quality_label=format_quality_label_legacy(None, requested_quality=quality),
        title=title,
    )

    if query.message:
        await query.message.edit_text(
            text=text,
            entities=entities,
            reply_markup=build_legacy_youtube_audio_keyboard(
                token=token,
                quality=quality,
                available_audio_langs=available_audio_langs,
                user_language_code=choice.get("language_code"),
            ),
            disable_web_page_preview=True,
        )


async def legacy_youtube_back_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(LEGACY_YOUTUBE_BACK_PREFIX):
        return

    token = data.replace(LEGACY_YOUTUBE_BACK_PREFIX, "", 1)

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        text, _ = render_text(TextKey.CALLBACK_CHOICE_EXPIRED)
        await query.answer(text, show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        text, _ = render_text(TextKey.CALLBACK_NOT_FOR_YOU, language_code=choice.get("language_code"))
        await query.answer(text, show_alert=True)
        return

    await query.answer()

    title = choice.get("title") or "YouTube видео"
    duration = choice.get("duration")

    text, entities = render_text(
        TextKey.YOUTUBE_CHOOSE_QUALITY,
        language_code=choice.get("language_code"),
        title=title,
        duration=format_duration_legacy(duration),
    )

    if query.message:
        await query.message.edit_text(
            text=text,
            entities=entities,
            reply_markup=build_legacy_youtube_quality_keyboard(token),
            disable_web_page_preview=True,
        )


async def legacy_youtube_audio_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(LEGACY_YOUTUBE_AUDIO_PREFIX):
        return

    try:
        payload = data.replace(LEGACY_YOUTUBE_AUDIO_PREFIX, "", 1)
        token, quality_raw, audio_lang = payload.split(":", 2)
        quality = int(quality_raw)
    except Exception:
        text, _ = render_text(TextKey.CALLBACK_INVALID_CHOICE)
        await query.answer(text, show_alert=True)
        return

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        text, _ = render_text(TextKey.CALLBACK_CHOICE_EXPIRED)
        await query.answer(text, show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        text, _ = render_text(TextKey.CALLBACK_NOT_FOR_YOU, language_code=choice.get("language_code"))
        await query.answer(text, show_alert=True)
        return

    available_audio_langs = set(choice.get("available_audio_langs") or [])

    if audio_lang != "auto" and audio_lang not in available_audio_langs:
        text, _ = render_text(TextKey.YOUTUBE_AUDIO_MISSING, language_code=choice.get("language_code"))
        await query.answer(text, show_alert=True)
        return

    await query.answer()

    title = choice.get("title") or "YouTube видео"
    audio_label = get_audio_caption_label(audio_lang) or "Original"

    logger.info(
        "Legacy YouTube audio selected | user_id=%s token=%s quality=%s audio=%s url=%s available=%s",
        user.id if user else None,
        token,
        quality,
        audio_lang,
        choice.get("url"),
        sorted(available_audio_langs),
    )

    if query.message:
        text, entities = render_text(
            TextKey.YOUTUBE_AUDIO_SELECTED,
            language_code=choice.get("language_code"),
            quality_label=format_quality_label_legacy(None, requested_quality=quality),
            audio_label=audio_label,
        )
        await query.message.edit_text(
            text=text,
            entities=entities,
            disable_web_page_preview=True,
        )

    if not query.message or not user:
        return

    await process_legacy_youtube_download(
        context=context,
        chat_id=query.message.chat_id,
        reply_to_message_id=None,
        url=choice.get("url"),
        title=title,
        requested_quality=quality,
        requested_audio_lang=audio_lang,
        user_id=user.id if user else None,
        language_code=choice.get("language_code"),
    )

def _build_legacy_youtube_cache_keys(
    *,
    url: str,
    requested_quality: int,
    requested_audio_lang: str,
) -> tuple[str, str, str]:
    source_key = build_source_key(
        Platform.YOUTUBE,
        original_url=url,
        resolved_url=url,
    )

    variant_key = build_variant_key(
        action=DownloadAction.DOWNLOAD_VIDEO_MAX,
        quality=requested_quality,
        audio_lang=requested_audio_lang or "auto",
    )

    bundle_key = build_bundle_key(source_key, variant_key)

    return source_key, variant_key, bundle_key


def _get_complete_legacy_youtube_cache_rows(rows) -> list:
    rows = list(rows or [])

    if not rows:
        return []

    if len(rows) != 1:
        return []

    row = rows[0]

    if not row["tg_file_id"] or not row["tg_send_type"]:
        return []

    return rows


def _build_legacy_youtube_caption(
    *,
    settings: Settings,
    title: str,
    url: str | None,
    duration=None,
    requested_quality: int | None = None,
    actual_height=None,
    requested_audio_lang: str | None = None,
) -> CaptionPayload:
    quality_label = format_quality_label_legacy(
        actual_height,
        requested_quality=requested_quality,
    )
    audio_label = get_audio_caption_label(requested_audio_lang)

    return build_content_caption(
        title=title or "YouTube видео",
        platform="youtube_shorts" if url and is_youtube_shorts_url(url) else "youtube",
        bot_username=settings.bot_username_text,
        source_url=url,
        quality=requested_quality,
        audio_label=audio_label,
        audio_lang=requested_audio_lang,
        media_type="video",
    )

async def process_legacy_youtube_download(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    reply_to_message_id: int | None,
    url: str,
    title: str,
    requested_quality: int,
    requested_audio_lang: str,
    user_id: int | None = None,
    language_code: str | None = None,
) -> None:
    settings: Settings = context.application.bot_data["settings"]

    wait_message = None
    request_id = None

    if await send_access_denied_if_needed(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        reply_to_message_id=reply_to_message_id,
    ):
        logger.info(
            "Legacy YouTube download blocked by access control | user_id=%s url=%s",
            user_id,
            url,
        )
        return

    source_key, variant_key, bundle_key = _build_legacy_youtube_cache_keys(
        url=url,
        requested_quality=requested_quality,
        requested_audio_lang=requested_audio_lang,
    )

    if user_id:
        try:
            increment_user_request(settings, user_id)
            request_id = create_download_request(
                settings,
                user_id=user_id,
                username=None,
                full_name="",
                language_code=language_code,
                original_url=url,
                resolved_url=url,
                platform=Platform.YOUTUBE.value,
                content_type="shorts" if is_youtube_shorts_url(url) else "video",
                action=DownloadAction.DOWNLOAD_VIDEO_MAX.value,
                source_key=source_key,
                variant_key=variant_key,
                bundle_key=bundle_key,
                title=title,
                requested_quality=requested_quality,
                requested_audio_lang=requested_audio_lang,
                status="started",
            )
        except Exception:
            logger.exception("Could not create legacy YouTube request row | user_id=%s url=%s", user_id, url)

    # ============================================================
    # 1. Cache hit: если YouTube-видео уже есть в Telegram file_id,
    #    сразу отправляем без скачивания.
    # ============================================================
    try:
        cached_rows = _get_complete_legacy_youtube_cache_rows(
            get_cached_bundle(settings, bundle_key)
        )

        if cached_rows:
            row = cached_rows[0]

            logger.info(
                "Legacy YouTube cache HIT | user_id=%s bundle_key=%s url=%s",
                user_id,
                bundle_key,
                url,
            )

            caption = _build_legacy_youtube_caption(
                settings=settings,
                title=row["title"] or title or "YouTube видео",
                url=url,
                duration=row["duration"],
                requested_quality=requested_quality,
                actual_height=row["height"],
                requested_audio_lang=requested_audio_lang,
            )

            try:
                await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
            except Exception:
                pass

            await send_cached_media(
                settings=settings,
                bot=context.bot,
                chat_id=chat_id,
                tg_file_id=row["tg_file_id"],
                send_type=row["tg_send_type"],
                caption=caption.text,
                caption_entities=caption.entities,
                reply_to_message_id=reply_to_message_id,
            )

            touch_cache_bundle(settings, bundle_key)

            if user_id:
                increment_user_cache_hit(settings, user_id)
                increment_user_download(settings, user_id)

            if request_id:
                try:
                    add_download_item(
                        settings,
                        request_id=request_id,
                        cache_key=row["cache_key"],
                        item_index=0,
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
                        items_total=1,
                        items_sent=1,
                    )
                except Exception:
                    logger.exception("Could not write legacy YouTube cache-hit request | request_id=%s", request_id)

            await maybe_send_after_download_ad(
                context=context,
                chat_id=chat_id,
                user_id=user_id,
            )
            return

        logger.info(
            "Legacy YouTube cache MISS | user_id=%s bundle_key=%s url=%s",
            user_id,
            bundle_key,
            url,
        )

    except Exception:
        logger.exception(
            "Legacy YouTube cache check failed, continue download | user_id=%s bundle_key=%s url=%s",
            user_id,
            bundle_key,
            url,
        )

    # ============================================================
    # 2. Cache miss: скачиваем, отправляем, сохраняем file_id.
    # ============================================================
    try:
        processing = processing_message("youtube", language_code=language_code)
        wait_message = await context.bot.send_message(
            chat_id=chat_id,
            text=processing.text,
            entities=processing.entities,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception:
        pass

    try:
        try:
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
        except Exception:
            pass

        temp_root = settings.base_dir / "media" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=temp_root) as tmpdir:
            def _download_operation(slot: int):
                def _download_with_proxy(proxy_url: str | None):
                    info = fetch_video_metadata_legacy(
                        settings,
                        url,
                        platform_auth_slot=slot,
                        proxy_url=proxy_url,
                    )
                    file_path, downloaded_info, result = download_video_smart_legacy(
                        settings,
                        url,
                        tmpdir,
                        info,
                        requested_quality,
                        requested_audio_lang,
                        platform_auth_slot=slot,
                        proxy_url=proxy_url,
                    )

                    if not file_path or not downloaded_info:
                        raise RuntimeError(result)

                    return info, file_path, downloaded_info, result

                proxy_result = run_with_proxy_rotation_sync(
                    settings=settings,
                    platform="youtube",
                    operation=_download_with_proxy,
                    operation_name="legacy_youtube_download",
                )
                return proxy_result.value

            auth_result = await run_with_cookie_rotation(
                context=context,
                url=url,
                platform="youtube",
                operation=_download_operation,
                operation_name="legacy_youtube_download",
            )

            info, file_path, downloaded_info, result = auth_result.value

            file_path = Path(file_path)

            final_title = downloaded_info.get("title") or title or "YouTube видео"
            duration = downloaded_info.get("duration")
            width = downloaded_info.get("width")
            height = downloaded_info.get("height")
            actual_height = downloaded_info.get("_actual_height") or height

            caption = _build_legacy_youtube_caption(
                settings=settings,
                title=final_title,
                url=url,
                duration=duration,
                requested_quality=requested_quality,
                actual_height=actual_height,
                requested_audio_lang=requested_audio_lang,
            )

            sent_file = await send_local_media(
                settings=settings,
                bot=context.bot,
                chat_id=chat_id,
                file_path=file_path,
                media_type="video",
                caption=caption.text,
                caption_entities=caption.entities,
                title=final_title,
                performer=downloaded_info.get("uploader") or downloaded_info.get("artist") or downloaded_info.get("creator"),
                duration=duration,
                width=width,
                height=height,
                reply_to_message_id=None,
            )

            count_cookie_success(settings, auth_result.platform, auth_result.slot)

            if user_id:
                increment_user_download(settings, user_id)

            cache_key = build_cache_key(bundle_key, 0)

            try:
                save_cached_item(
                    settings,
                    cache_key=cache_key,
                    bundle_key=bundle_key,
                    source_key=source_key,
                    variant_key=variant_key,
                    platform=Platform.YOUTUBE.value,
                    content_type="shorts" if is_youtube_shorts_url(url) else "video",
                    media_type="video",
                    original_url=url,
                    resolved_url=url,
                    title=final_title,
                    author=downloaded_info.get("uploader") or downloaded_info.get("artist") or downloaded_info.get("creator"),
                    item_index=0,
                    item_total=1,
                    tg_file_id=sent_file.file_id,
                    tg_file_unique_id=sent_file.file_unique_id,
                    tg_send_type=sent_file.send_type,
                    file_size=file_path.stat().st_size,
                    width=width,
                    height=height,
                    duration=duration,
                    quality=requested_quality,
                    audio_lang=requested_audio_lang,
                )

                logger.info(
                    "Legacy YouTube cache SAVED | user_id=%s bundle_key=%s send_type=%s file=%s",
                    user_id,
                    bundle_key,
                    sent_file.send_type,
                    file_path,
                )

            except Exception:
                logger.exception(
                    "Legacy YouTube cache save failed | user_id=%s bundle_key=%s url=%s",
                    user_id,
                    bundle_key,
                    url,
                )

            if request_id:
                try:
                    add_download_item(
                        settings,
                        request_id=request_id,
                        cache_key=cache_key,
                        item_index=0,
                        media_type="video",
                        status="sent",
                        cache_status="miss",
                        tg_file_id=sent_file.file_id,
                        tg_send_type=sent_file.send_type,
                        file_size=file_path.stat().st_size,
                        width=width,
                        height=height,
                        duration=duration,
                    )
                    update_download_request(
                        settings,
                        request_id,
                        status="sent",
                        cache_status="miss",
                        items_total=1,
                        items_sent=1,
                    )
                except Exception:
                    logger.exception("Could not write legacy YouTube fresh request | request_id=%s", request_id)

        if wait_message:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=wait_message.message_id,
                )
            except Exception:
                pass

        await maybe_send_after_download_ad(
            context=context,
            chat_id=chat_id,
            user_id=user_id,
        )

    except Exception as e:
        logger.exception("Legacy YouTube download failed | url=%s", url)

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
                logger.exception("Could not update failed legacy YouTube request | request_id=%s", request_id)

        public_error = public_download_error_message(e, "youtube", language_code=language_code)
        await context.bot.send_message(
            chat_id=chat_id,
            text=public_error.text,
            entities=public_error.entities,
        )
