import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yt_dlp

from app.config import Settings
from app.downloader.content_types import DownloadAction
from app.downloader.cookies import apply_platform_cookies
from app.downloader.routing import RouteDecision

import subprocess
from app.downloader.pinterest import (
    is_pinterest_url,
    download_pinterest_pin,
)

from app.downloader.tiktok_photo import (
    is_tiktok_photo_url,
    download_tiktok_photo_post,
)

from app.downloader.instagram_post import (
    is_instagram_post_url,
    download_instagram_post,
)

from app.downloader.instagram_story import (
    is_instagram_story_url,
    download_instagram_story,
)


logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "avif"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "mkv", "m4v"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "opus", "ogg", "wav"}


def _is_google_sorry_or_youtube_consent_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host in {"google.com", "www.google.com"} and path.startswith("/sorry"):
        return True

    return host == "consent.youtube.com"


@dataclass(frozen=True)
class DownloadedMedia:
    path: Path
    media_type: str
    item_index: int
    item_total: int
    title: Optional[str] = None
    author: Optional[str] = None
    album_title: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    file_size: Optional[int] = None

def _get_tiktok_video_format() -> str:
    """
    Для TikTok НЕ берём слепо best, потому что best часто выбирает bytevc1/h265.
    Telegram может проигрывать такой файл с фризами.
    Сначала просим h264/mp4 video + лучшую audio-дорожку, чтобы звук в
    отправленном видео был того же уровня, что и в отдельном audio-сообщении.
    Потом fallback на цельные mp4.
    """
    return (
        "best[ext=mp4][vcodec^=h264][acodec!=none]/"
        "best[ext=mp4][vcodec*=avc1][acodec!=none]/"
        "best[ext=mp4][vcodec!=bytevc1][vcodec!=h265][vcodec!=hevc][acodec!=none]/"
        "best[ext=mp4][acodec!=none]/"
        "best"
    )

def _clean_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for item in output_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            logger.warning("Could not remove temp item: %s", item)


def _detect_media_type(path: Path, forced_action: DownloadAction | None = None) -> str:
    ext = path.suffix.lower().lstrip(".")

    if forced_action == DownloadAction.DOWNLOAD_AUDIO:
        return "audio"

    if ext in IMAGE_EXTENSIONS:
        return "photo"

    if ext in VIDEO_EXTENSIONS:
        return "video"

    if ext in AUDIO_EXTENSIONS:
        return "audio"

    return "document"


def _route_platform_value(route: RouteDecision) -> str:
    return getattr(route.platform, "value", str(route.platform))


def _route_content_type_value(route: RouteDecision) -> str:
    return getattr(route.content_type, "value", str(route.content_type))


def _is_youtube_music_album_route(route: RouteDecision) -> bool:
    return (
        _route_platform_value(route) == "youtube"
        and route.action == DownloadAction.DOWNLOAD_ALBUM
        and _route_content_type_value(route) == "music_page"
    )


def _normalize_audio_lang_for_download(lang: str | None) -> str:
    if not lang:
        return ""

    lang = str(lang).lower().strip()

    if lang.startswith("a."):
        lang = lang[2:]

    return lang.split("-")[0]


def _youtube_audio_candidates(audio_lang: str | None) -> list[str]:
    audio_lang = _normalize_audio_lang_for_download(audio_lang)

    if audio_lang not in ("ru", "en"):
        return [
            "bestaudio[ext=m4a]",
            "bestaudio",
        ]

    return [
        f"bestaudio[language={audio_lang}][ext=m4a]",
        f"bestaudio[language^={audio_lang}][ext=m4a]",
        f"bestaudio[language={audio_lang}]",
        f"bestaudio[language^={audio_lang}]",
    ]


def _build_youtube_format(
    quality: int | None,
    audio_lang: str | None,
    audio_format_id: str | None = None,
) -> str:
    quality = quality or 720

    if quality == 1081:
        qualities = [1080, 720, 480, 360]
    elif quality >= 1080:
        qualities = [1080, 720, 480, 360]
    else:
        qualities = [720, 480, 360]

    audio_candidates = _youtube_audio_candidates(audio_lang)

    attempts: list[str] = []

    for q in qualities:
        for audio_fmt in audio_candidates:
            attempts.append(f"bestvideo[height<={q}][ext=mp4][vcodec^=avc1]+{audio_fmt}")
            attempts.append(f"bestvideo[height<={q}][ext=mp4]+{audio_fmt}")
            attempts.append(f"bestvideo[height<={q}]+{audio_fmt}")

        attempts.extend([
            f"best[height<={q}][ext=mp4]/best[height<={q}]",
        ])

    return "/".join(attempts)


def _build_format(
    route: RouteDecision,
    quality: int | None,
    audio_lang: str | None,
    audio_format_id: str | None = None,
) -> str | None:
    platform = _route_platform_value(route)
    action = route.action

    # TikTok video:
    # Не берём слепо best, потому что TikTok часто отдаёт bytevc1 / h265.
    # Telegram может проигрывать такие видео с фризами.
    # Поэтому сначала просим h264 / avc1 mp4.
    if platform == "tiktok" and action == DownloadAction.DOWNLOAD_VIDEO_MAX:
        return _get_tiktok_video_format()

    if platform == "youtube" and action == DownloadAction.DOWNLOAD_VIDEO_MAX:
        return _build_youtube_format(1081, audio_lang, audio_format_id)

    if action == DownloadAction.ASK_YOUTUBE_QUALITY:
        return _build_youtube_format(quality, audio_lang, audio_format_id)

    if action == DownloadAction.DOWNLOAD_AUDIO or _is_youtube_music_album_route(route):
        return "bestaudio[ext=m4a]/bestaudio/best"

    if action in {
        DownloadAction.DOWNLOAD_VIDEO_MAX,
        DownloadAction.DOWNLOAD_STORY,
    }:
        return (
            "best[ext=mp4][vcodec!=none][acodec!=none]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best"
        )

    if action in {
        DownloadAction.DOWNLOAD_PHOTO,
        DownloadAction.DOWNLOAD_ALBUM,
    }:
        return "best"

    return "best"


def _collect_downloaded_files(output_dir: Path) -> list[Path]:
    ignored_suffixes = {".part", ".ytdl", ".temp", ".tmp"}

    files = []

    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() in ignored_suffixes:
            continue

        if path.name.endswith(".part"):
            continue

        files.append(path)

    files.sort(key=lambda p: (p.name, p.stat().st_size))

    return files

def _should_fix_mp4_for_telegram(route: RouteDecision, media_type: str, path: Path) -> bool:
    if media_type != "video":
        return False

    if path.suffix.lower() != ".mp4":
        return False

    if route.platform.value == "instagram":
        return True

    return False


def _fix_mp4_for_telegram(input_path: Path) -> Path:
    output_path = input_path.with_name(input_path.stem + "_tg_fixed.mp4")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
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
            timeout=180,
        )

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("MP4 fixed for Telegram | input=%s output=%s", input_path, output_path)
            return output_path

        logger.warning(
            "MP4 fix failed | input=%s | returncode=%s | stderr=%s",
            input_path,
            result.returncode,
            result.stderr[-1000:],
        )

    except Exception as e:
        logger.warning("MP4 fix crashed | input=%s | error=%s", input_path, e)

    return input_path

def _extract_playlist_entries(downloaded_info) -> list[dict]:
    if not isinstance(downloaded_info, dict):
        return []

    entries = downloaded_info.get("entries") or []

    result = []

    for entry in entries:
        if isinstance(entry, dict):
            result.append(entry)

    return result


def _as_metadata_text(value) -> str | None:
    if value is None:
        return None

    if isinstance(value, (list, tuple, set)):
        parts = []

        for item in value:
            if item is None:
                continue

            if isinstance(item, dict):
                item = (
                    item.get("name")
                    or item.get("title")
                    or item.get("artist")
                    or item.get("id")
                )

            text = str(item).strip() if item is not None else ""

            if text:
                parts.append(text)

        return ", ".join(parts) or None

    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("artist")
            or value.get("id")
        )

        if value is None:
            return None

    value = str(value).strip()
    return value or None


def _looks_like_tiktok_generated_title(value: str | None) -> bool:
    text = str(value or "").strip().lower()

    return bool(re.fullmatch(r"tiktok\s+video\s+#?\d+", text))


def _best_tiktok_title(info: dict | None, fallback: str | None = None) -> str | None:
    if not isinstance(info, dict):
        return fallback

    candidates = [
        info.get("description"),
        info.get("fulltitle"),
        info.get("alt_title"),
        info.get("caption"),
        info.get("title"),
    ]

    for candidate in candidates:
        text = _as_metadata_text(candidate)

        if text and not _looks_like_tiktok_generated_title(text):
            return text

    return fallback


def _entry_title(entry: dict | None, fallback: str | None = None) -> str | None:
    if not entry:
        return fallback

    return _as_metadata_text(
        entry.get("track")
        or entry.get("title")
        or entry.get("alt_title")
        or fallback
    )


def _entry_author(entry: dict | None, fallback: str | None = None) -> str | None:
    if not entry:
        return fallback

    return _as_metadata_text(
        entry.get("artist")
        or entry.get("artists")
        or entry.get("uploader")
        or entry.get("creator")
        or entry.get("channel")
        or fallback
    )


def _entry_album_title(entry: dict | None, fallback: str | None = None) -> str | None:
    if not entry:
        return fallback

    return _as_metadata_text(
        entry.get("album")
        or entry.get("playlist_title")
        or entry.get("playlist")
        or fallback
    )


def _entry_duration(entry: dict | None, fallback=None):
    if not entry:
        return fallback

    return entry.get("duration") or fallback


def _entry_width(entry: dict | None, fallback=None):
    if not entry:
        return fallback

    return entry.get("width") or fallback


def _entry_height(entry: dict | None, fallback=None):
    if not entry:
        return fallback

    return entry.get("height") or fallback


def _entry_file_id(entry: dict | None) -> str | None:
    if not entry:
        return None

    value = (
        entry.get("id")
        or entry.get("display_id")
        or entry.get("url")
    )

    if not value:
        return None

    return str(value)


def _file_entry_id_from_path(path: Path) -> str | None:
    """
    output_template сейчас такой:
    000_videoid.ext

    Поэтому из имени файла можно вытащить videoid после первого "_".
    """
    stem = path.stem

    if "_" not in stem:
        return None

    return stem.split("_", 1)[1] or None


def _build_entries_by_id(entries: list[dict]) -> dict[str, dict]:
    result = {}

    for entry in entries:
        entry_id = _entry_file_id(entry)

        if entry_id:
            result[entry_id] = entry

    return result


def _match_entry_for_file(
    *,
    file_path: Path,
    file_index: int,
    entries: list[dict],
    entries_by_id: dict[str, dict],
) -> dict | None:
    file_entry_id = _file_entry_id_from_path(file_path)

    if file_entry_id and file_entry_id in entries_by_id:
        return entries_by_id[file_entry_id]

    if 0 <= file_index < len(entries):
        return entries[file_index]

    return None

def download_media_bundle(
    *,
    settings: Settings,
    url: str,
    route: RouteDecision,
    output_dir: Path,
    quality: int | None = None,
    audio_lang: str | None = None,
    audio_format_id: str | None = None,
    platform_auth_slot: int | None = None,
    playlist_item_limit: int | None = None,
    proxy_url: str | None = None,
) -> list[DownloadedMedia]:
    _clean_output_dir(output_dir)
    platform = getattr(route.platform, "value", str(route.platform))
    action = getattr(route.action, "value", str(route.action))
    content_type = getattr(route.content_type, "value", str(route.content_type))

    if platform == "youtube" and _is_google_sorry_or_youtube_consent_url(url):
        raise RuntimeError(
            "YouTube temporarily limited access: google sorry/consent page returned instead of media"
        )

    if platform == "pinterest" or is_pinterest_url(url):
            paths = download_pinterest_pin(
                settings=settings,
                url=url,
                output_dir=output_dir,
                platform_auth_slot=platform_auth_slot,
            )

            result = []
            sendable_paths = []

            for path in paths:
                suffix = path.suffix.lower()

                if suffix in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm"}:
                    sendable_paths.append(path)

            total = len(sendable_paths)

            for index, path in enumerate(sendable_paths):
                suffix = path.suffix.lower()

                if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
                    media_type = "photo"
                elif suffix in {".mp4", ".mov", ".m4v", ".webm"}:
                    media_type = "video"
                else:
                    continue

                result.append(
                    DownloadedMedia(
                        path=path,
                        media_type=media_type,
                        item_index=index,
                        item_total=total,
                        title=route.title or "Pinterest",
                        file_size=path.stat().st_size,
                    )
                )

            if not result:
                raise RuntimeError("Pinterest downloaded but no sendable media files found")

            return result

    # Instagram stories.
    # ВАЖНО: ставим до Instagram /p/ post/carousel,
    # чтобы story не улетела в post-downloader.
    if platform == "instagram" and is_instagram_story_url(url):
        paths = download_instagram_story(
            settings=settings,
            url=url,
            output_dir=output_dir,
            platform_auth_slot=platform_auth_slot,
        )

        result = []
        sendable_paths = []

        for path in paths:
            suffix = path.suffix.lower()

            if suffix in {
                ".jpg", ".jpeg", ".png", ".webp",
                ".mp4", ".mov", ".m4v", ".webm",
                ".m4a", ".mp3", ".aac", ".opus", ".ogg",
            }:
                sendable_paths.append(path)

        # Сначала фото/видео, потом аудио.
        sendable_paths.sort(
            key=lambda p: (
                1 if p.suffix.lower() in {".m4a", ".mp3", ".aac", ".opus", ".ogg"} else 0,
                p.name.lower(),
            )
        )

        total = len(sendable_paths)

        for index, path in enumerate(sendable_paths):
            suffix = path.suffix.lower()

            if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
                media_type = "photo"
            elif suffix in {".mp4", ".mov", ".m4v", ".webm"}:
                media_type = "video"
            elif suffix in {".m4a", ".mp3", ".aac", ".opus", ".ogg"}:
                media_type = "audio"
            else:
                continue

            result.append(
                DownloadedMedia(
                    path=path,
                    media_type=media_type,
                    item_index=index,
                    item_total=total,
                    title=route.title or "Instagram story",
                    file_size=path.stat().st_size,
                )
            )

        if not result:
            raise RuntimeError("Instagram story downloaded but no sendable media files found")

        return result

     # Instagram /p/ post/carousel.
    # ВАЖНО: не отправляем это в обычный yt-dlp video download,
    # потому что yt-dlp часто забирает только видео и игнорирует фото.
    if platform == "instagram" and (
        is_instagram_post_url(url)
        or action in {"download_album", "download_photo"}
        or content_type in {"post", "album", "photo", "carousel"}
    ):
        paths = download_instagram_post(
            settings=settings,
            url=url,
            output_dir=output_dir,
            platform_auth_slot=platform_auth_slot,
        )

        result = []

        sendable_paths = []

        for path in paths:
            suffix = path.suffix.lower()

            if suffix in {
                ".jpg", ".jpeg", ".png", ".webp",
                ".mp4", ".mov", ".m4v", ".webm",
                ".m4a", ".mp3", ".aac", ".opus", ".ogg",
            }:
                sendable_paths.append(path)

        # Сначала фото/видео, потом аудио.
        sendable_paths.sort(
            key=lambda p: (
                1 if p.suffix.lower() in {".m4a", ".mp3", ".aac", ".opus", ".ogg"} else 0,
                p.name.lower(),
            )
        )

        total = len(sendable_paths)

        for index, path in enumerate(sendable_paths):
            suffix = path.suffix.lower()

            if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
                media_type = "photo"
            elif suffix in {".mp4", ".mov", ".m4v", ".webm"}:
                media_type = "video"
            elif suffix in {".m4a", ".mp3", ".aac", ".opus", ".ogg"}:
                media_type = "audio"
            else:
                continue
            
            result.append(
                DownloadedMedia(
                    path=path,
                    media_type=media_type,
                    item_index=index,
                    item_total=total,
                    title=route.title or "Instagram post",
                    file_size=path.stat().st_size,
                )
            )

        if not result:
            raise RuntimeError("Instagram post downloaded but no sendable media files found")

        return result
    
    # TikTok photo/slideshow posts.
    # ВАЖНО: не отправляем это в yt-dlp video download.
    if platform == "tiktok" and (
        is_tiktok_photo_url(url)
        or action in {"download_album", "download_photo"}
        or content_type in {"post", "album", "photo", "photo_post", "slideshow"}
    ):
        paths = download_tiktok_photo_post(
            settings=settings,
            url=url,
            output_dir=output_dir,
            platform_auth_slot=platform_auth_slot,
        )

        result = []

        total = len(paths)

        sendable_paths = []

        for path in paths:
            suffix = path.suffix.lower()

            if suffix in {
                ".jpg", ".jpeg", ".png", ".webp",
                ".mp4", ".mov", ".m4v", ".webm",
                ".m4a", ".mp3", ".aac", ".opus", ".ogg",
            }:
                sendable_paths.append(path)

        # Важно: сначала фото/видео, потом аудио.
        sendable_paths.sort(
            key=lambda p: (
                1 if p.suffix.lower() in {".m4a", ".mp3", ".aac", ".opus", ".ogg"} else 0,
                p.name.lower(),
            )
        )

        single_live_video = (
            len(sendable_paths) == 1
            and sendable_paths[0].suffix.lower() in {".mp4", ".mov", ".m4v", ".webm"}
        )

        total = len(sendable_paths)

        for index, path in enumerate(sendable_paths):
            suffix = path.suffix.lower()

            if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
                media_type = "photo"
            elif suffix in {".mp4", ".mov", ".m4v", ".webm"}:
                media_type = "live_photo" if single_live_video else "video"
            elif suffix in {".m4a", ".mp3", ".aac", ".opus", ".ogg"}:
                media_type = "audio"
            else:
                continue
            
            result.append(
                DownloadedMedia(
                    path=path,
                    media_type=media_type,
                    item_index=index,
                    item_total=total,
                    title=route.title or "TikTok media",
                    file_size=path.stat().st_size,
                )
            )

        if not result:
            raise RuntimeError("TikTok photo post downloaded but no sendable media files found")

        return result
    
    output_template = str(output_dir / "%(playlist_index|000)s_%(id|media)s.%(ext)s")

    fmt = _build_format(route, quality, audio_lang, audio_format_id)

    ydl_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False if route.action == DownloadAction.DOWNLOAD_ALBUM else True,
        "format": fmt,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "http_chunk_size": 10 * 1024 * 1024,
        "ignoreerrors": True,
        "ignore_no_formats_error": True,
        "merge_output_format": "mp4",
    }

    if playlist_item_limit and route.action == DownloadAction.DOWNLOAD_ALBUM:
        ydl_opts["playlistend"] = max(1, int(playlist_item_limit))

    if route.action == DownloadAction.DOWNLOAD_AUDIO or _is_youtube_music_album_route(route):
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ]

    ydl_opts = apply_platform_cookies(
        settings,
        url,
        ydl_opts,
        platform_auth_slot=platform_auth_slot,
        proxy_url_override=proxy_url,
    )
    logger.info(
        "yt-dlp options prepared | url=%s cookiefile=%s",
        url,
        ydl_opts.get("cookiefile"),
    )
    logger.info(
        "Download started | url=%s action=%s format=%s quality=%s audio=%s audio_format_id=%s",
        url,
        route.action.value,
        fmt,
        quality,
        audio_lang,
        audio_format_id,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        downloaded_info = ydl.extract_info(url, download=True)

    if isinstance(downloaded_info, dict):
        downloaded_info["_platform_auth_name"] = ydl_opts.get("_platform_auth_name")
        downloaded_info["_platform_auth_slot"] = ydl_opts.get("_platform_auth_slot")

    files = _collect_downloaded_files(output_dir)

    if not files:
        if platform == "youtube" and "music.youtube.com" in str(url).lower():
            raise RuntimeError(
                "YouTube temporarily limited access: download completed but no files were created"
            )

        raise RuntimeError("download completed but no files were created")

    max_size = settings.max_file_size_mb * 1024 * 1024

    result: list[DownloadedMedia] = []
    item_total = len(files)

    title = None
    author = None
    album_title = None
    duration = None
    width = None
    height = None

    if isinstance(downloaded_info, dict):
        title = _as_metadata_text(downloaded_info.get("title"))
        album_title = _as_metadata_text(
            downloaded_info.get("album")
            or downloaded_info.get("playlist_title")
            or downloaded_info.get("playlist")
            or downloaded_info.get("title")
        )

        if platform == "tiktok":
            title = _best_tiktok_title(downloaded_info, title)

        author = _as_metadata_text(
            downloaded_info.get("uploader")
            or downloaded_info.get("artist")
            or downloaded_info.get("creator")
        )
        duration = downloaded_info.get("duration")
        width = downloaded_info.get("width")
        height = downloaded_info.get("height")

    entries = _extract_playlist_entries(downloaded_info)
    entries_by_id = _build_entries_by_id(entries)

    for index, file_path in enumerate(files):
        media_type = _detect_media_type(file_path, route.action)
        entry = _match_entry_for_file(
            file_path=file_path,
            file_index=index,
            entries=entries,
            entries_by_id=entries_by_id,
        )

        if _should_fix_mp4_for_telegram(route, media_type, file_path):
            file_path = _fix_mp4_for_telegram(file_path)
            media_type = _detect_media_type(file_path, route.action)
        
        file_size = file_path.stat().st_size

        if file_size > max_size:
            raise RuntimeError(
                f"file too large: {file_size / 1024 / 1024:.1f} MB, limit {settings.max_file_size_mb} MB"
            )

        result.append(
            DownloadedMedia(
                path=file_path,
                media_type=media_type,
                item_index=index,
                item_total=item_total,
                title=_entry_title(entry, title),
                author=_entry_author(entry, author),
                album_title=_entry_album_title(entry, album_title),
                width=_entry_width(entry, width),
                height=_entry_height(entry, height),
                duration=_entry_duration(entry, duration),
                file_size=file_size,
            )
        )

    logger.info(
        "Download finished | files=%s media_types=%s",
        len(result),
        [item.media_type for item in result],
    )

    return result
