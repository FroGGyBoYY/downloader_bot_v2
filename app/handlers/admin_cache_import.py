import logging
import re
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.cache_repo import save_cached_item
from app.downloader.cache_keys import build_bundle_key, build_cache_key, build_source_key, build_variant_key
from app.downloader.content_types import DownloadAction, Platform
from app.services.legacy_youtube_service import is_youtube_shorts_url


logger = logging.getLogger(__name__)


ADMIN_RECEIVE_VIDEO_KEY = "admin_receive_video_user_ids"
URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
SUPPORTED_AUDIO_LANGS = ("ru", "en", "es", "ar", "zh", "th")


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return is_admin(settings, user_id)


def _enabled_users(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    return context.application.bot_data.setdefault(ADMIN_RECEIVE_VIDEO_KEY, set())


def _extract_youtube_url(text: str | None) -> str | None:
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,);]}>")
        host = urlparse(url).netloc.lower()

        if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
            if host.startswith("music.youtube.com"):
                continue

            return url

    return None


def _strip_title_prefix(line: str) -> str:
    return re.sub(r"^[^\wА-Яа-яЁё0-9]+", "", line).strip()


def _extract_title(text: str | None, fallback: str = "YouTube видео") -> str:
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        lower = line.lower()

        if "http://" in lower or "https://" in lower:
            continue

        if any(marker in lower for marker in ("качество", "озвучка", "длительность", "quality", "audio")):
            continue

        if "@" in line and "bot" in lower:
            continue

        title = _strip_title_prefix(line)

        if title:
            return title[:250]

    return fallback


def _parse_quality(text: str | None, *, video_height: int | None, video_width: int | None, url: str) -> int:
    value = (text or "").lower()

    if "1080p hq" in value or "1080 hq" in value:
        return 1081

    match = re.search(r"\b(2160|1440|1080|720|480|360)\s*p\b", value)

    if match:
        quality = int(match.group(1))

        if quality >= 1080:
            return 1080

        return quality

    if is_youtube_shorts_url(url):
        return 1081

    height = int(video_height or 0)
    width = int(video_width or 0)
    side = min(height, width) if height and width else (height or width)

    if side >= 1000:
        return 1080

    return 720


def _parse_audio_lang(text: str | None) -> str:
    value = (text or "").lower()

    audio_lines = [
        line.lower()
        for line in (text or "").splitlines()
        if "озвуч" in line.lower() or "audio" in line.lower() or "original" in line.lower()
    ]
    haystack = "\n".join(audio_lines) if audio_lines else value

    if "original" in haystack or "ориг" in haystack:
        return "auto"

    for lang in SUPPORTED_AUDIO_LANGS:
        if re.search(rf"(^|[^a-z]){lang}([^a-z]|$)", haystack):
            return lang

    return "auto"


def _build_import_cache_keys(url: str, quality: int, audio_lang: str) -> tuple[str, str, str, str]:
    source_key = build_source_key(
        Platform.YOUTUBE,
        original_url=url,
        resolved_url=url,
    )
    variant_key = build_variant_key(
        action=DownloadAction.DOWNLOAD_VIDEO_MAX,
        quality=quality,
        audio_lang=audio_lang or "auto",
    )
    bundle_key = build_bundle_key(source_key, variant_key)
    cache_key = build_cache_key(bundle_key, 0)
    return source_key, variant_key, bundle_key, cache_key


async def admin_receive_video_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    if not update.message:
        return

    if not _is_admin(settings, user.id if user else None):
        await update.message.reply_text("Эта команда доступна только админу.")
        return

    _enabled_users(context).add(user.id)
    await update.message.reply_text(
        "Режим приема YouTube-видео включен. Пересылай видео из старого бота с caption, где есть ссылка."
    )


async def admin_receive_video_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    if not update.message:
        return

    if not _is_admin(settings, user.id if user else None):
        await update.message.reply_text("Эта команда доступна только админу.")
        return

    _enabled_users(context).discard(user.id)
    await update.message.reply_text("Режим приема YouTube-видео выключен.")


async def admin_receive_video_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message or not user or user.id not in _enabled_users(context):
        return

    if not _is_admin(settings, user.id):
        return

    if not message.video:
        await message.reply_text("Жду именно video-сообщение со ссылкой на YouTube в caption.")
        return

    caption = message.caption or ""
    url = _extract_youtube_url(caption)

    if not url:
        await message.reply_text("Не нашел YouTube-ссылку в caption. Кеш не записан.")
        return

    video = message.video
    quality = _parse_quality(caption, video_height=video.height, video_width=video.width, url=url)
    audio_lang = _parse_audio_lang(caption)
    title = _extract_title(caption)
    source_key, variant_key, bundle_key, cache_key = _build_import_cache_keys(url, quality, audio_lang)

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
        title=title,
        author=None,
        item_index=0,
        item_total=1,
        tg_file_id=video.file_id,
        tg_file_unique_id=video.file_unique_id,
        tg_send_type="video",
        file_size=video.file_size,
        width=video.width,
        height=video.height,
        duration=video.duration,
        quality=quality,
        audio_lang=audio_lang,
    )

    logger.info(
        "Admin imported YouTube video cache | admin_id=%s url=%s quality=%s audio=%s bundle_key=%s",
        user.id,
        url,
        quality,
        audio_lang,
        bundle_key,
    )

    await message.reply_text(
        "\n".join([
            "Видео добавлено в кеш.",
            f"Название: {title}",
            f"Качество: {'1080p HQ' if quality == 1081 else str(quality) + 'p'}",
            f"Озвучка: {audio_lang}",
            f"URL: {url}",
        ])
    )
