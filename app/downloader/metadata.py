import logging
import re
from typing import Any
from urllib.parse import urlparse

import yt_dlp

from app.config import Settings
from app.downloader.cookies import apply_platform_cookies


logger = logging.getLogger(__name__)


def _is_google_sorry_or_youtube_consent_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host in {"google.com", "www.google.com"} and path.startswith("/sorry"):
        return True

    return host == "consent.youtube.com"


def _metadata_text(value) -> str | None:
    if value is None:
        return None

    text = str(value).replace("\n", " ").strip()
    text = " ".join(text.split())
    return text or None


def _looks_like_tiktok_generated_title(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return bool(re.fullmatch(r"tiktok\s+video\s+#?\d+", text))


def _fix_tiktok_title(info: dict[str, Any], url: str) -> None:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    webpage_url = str(info.get("webpage_url") or info.get("original_url") or url).lower()

    if "tiktok" not in extractor and "tiktok.com" not in webpage_url:
        return

    title = _metadata_text(info.get("title"))

    if title and not _looks_like_tiktok_generated_title(title):
        return

    for key in ("description", "fulltitle", "alt_title", "caption"):
        value = _metadata_text(info.get(key))

        if value and not _looks_like_tiktok_generated_title(value):
            info["title"] = value
            return


def _build_metadata_opts(
    settings: Settings,
    url: str,
    *,
    platform_auth_slot: int | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "skip_download": True,
        "socket_timeout": 25,
        "retries": 2,
        "extract_flat": False,
        "ignoreerrors": True,
        "ignore_no_formats_error": True,
    }

    return apply_platform_cookies(settings, url, opts, platform_auth_slot=platform_auth_slot)


def fetch_metadata(settings: Settings, url: str, *, platform_auth_slot: int | None = None) -> dict[str, Any]:
    if _is_google_sorry_or_youtube_consent_url(url):
        raise RuntimeError(
            "YouTube temporarily limited access: google sorry/consent page returned instead of media"
        )

    opts = _build_metadata_opts(settings, url, platform_auth_slot=platform_auth_slot)

    logger.info("Fetching metadata | url=%s", url)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned empty metadata")

    info["_original_url"] = url
    _fix_tiktok_title(info, url)

    resolved_url = (
        info.get("webpage_url")
        or info.get("original_url")
        or info.get("url")
        or url
    )

    info["_resolved_url"] = resolved_url

    entries = info.get("entries") or []

    logger.info(
        "Metadata fetched | extractor=%s id=%s title=%s entries=%s duration=%s ext=%s resolved_url=%s",
        info.get("extractor_key") or info.get("extractor"),
        info.get("id"),
        info.get("title"),
        len(entries) if isinstance(entries, list) else 0,
        info.get("duration"),
        info.get("ext"),
        resolved_url,
    )

    return info


def try_fetch_metadata(
    settings: Settings,
    original_url: str,
    resolved_url: str | None = None,
    *,
    platform_auth_slot: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Пытаемся получить metadata:
    1. Сначала по resolved_url, если он отличается от original.
    2. Потом по original_url.
    Возвращаем (info, error_text).
    """
    urls_to_try: list[str] = []

    if resolved_url and resolved_url != original_url:
        urls_to_try.append(resolved_url)

    urls_to_try.append(original_url)

    last_error: str | None = None

    for url in urls_to_try:
        try:
            return fetch_metadata(settings, url, platform_auth_slot=platform_auth_slot), None
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.exception("Metadata attempt failed | url=%s | error=%s", url, e)

    return None, last_error


def format_duration(seconds: Any) -> str:
    if seconds is None:
        return "unknown"

    try:
        seconds = int(float(seconds))
    except Exception:
        return "unknown"

    if seconds <= 0:
        return "unknown"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"
