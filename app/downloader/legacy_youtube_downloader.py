import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yt_dlp

from app.config import Settings
from app.downloader.cookies import apply_platform_cookies


logger = logging.getLogger(__name__)

SUPPORTED_YOUTUBE_AUDIO_LANGS = ("ru", "en", "es", "ar", "zh", "th")

YOUTUBE_AUDIO_LABELS = {
    "ru": "RU",
    "en": "EN",
    "es": "ES",
    "ar": "AR",
    "zh": "ZH",
    "th": "TH",
    "auto": "Original",
}

def is_youtube_url_legacy(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    except Exception:
        return False


def normalize_audio_lang(lang: Optional[str]) -> str:
    if not lang:
        return ""

    lang = str(lang).lower().strip()

    if lang.startswith("a."):
        lang = lang[2:]

    return lang.split("-")[0]


def get_audio_caption_label(lang_code: Optional[str]) -> Optional[str]:
    lang_code = normalize_audio_lang(lang_code)

    if lang_code in YOUTUBE_AUDIO_LABELS:
        return YOUTUBE_AUDIO_LABELS[lang_code]

    return None


def get_audio_missing_text(lang_code: str) -> str:
    label = get_audio_caption_label(lang_code) or lang_code.upper()

    return f"Озвучки {label} нет у этого видео. Выбери другую."


def fetch_video_metadata_legacy(
    settings: Settings,
    url: str,
    *,
    platform_auth_slot: int | None = None,
) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 2,
    }

    opts = apply_platform_cookies(settings, url, opts, platform_auth_slot=platform_auth_slot)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if isinstance(info, dict) and "entries" in info and info["entries"]:
        info = info["entries"][0]

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned empty metadata")

    info["_platform_auth_name"] = opts.get("_platform_auth_name")
    info["_platform_auth_slot"] = opts.get("_platform_auth_slot")

    return info


def get_available_youtube_audio_langs(info: dict) -> set[str]:
    available = set()

    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue

        acodec = f.get("acodec")

        if not acodec or acodec == "none":
            continue

        lang = normalize_audio_lang(f.get("language"))

        if lang in SUPPORTED_YOUTUBE_AUDIO_LANGS:
            available.add(lang)

    return available


def build_youtube_audio_format_candidates(audio_lang: Optional[str]) -> list[str]:
    audio_lang = normalize_audio_lang(audio_lang)

    if audio_lang not in SUPPORTED_YOUTUBE_AUDIO_LANGS:
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


def format_duration_legacy(seconds) -> str:
    if seconds is None:
        return "неизвестно"

    try:
        seconds = int(float(seconds))
    except Exception:
        return "неизвестно"

    if seconds <= 0:
        return "неизвестно"

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h:
        return f"{h}:{m:02d}:{s:02d}"

    return f"{m}:{s:02d}"


def format_quality_label_legacy(
    height,
    *,
    requested_quality: Optional[int] = None,
) -> Optional[str]:
    if requested_quality == 1081:
        return "1080p HQ"

    if requested_quality == 1080:
        return "1080p"

    if requested_quality == 720:
        return "720p"

    if height is None:
        return None

    try:
        height = int(float(height))
    except Exception:
        return None

    if height <= 0:
        return None

    if height >= 1800:
        return "1080p"
    elif 900 <= height <= 1300:
        return "1080p"
    elif 650 <= height <= 850:
        return "720p"
    elif 430 <= height <= 560:
        return "480p"
    elif 300 <= height <= 420:
        return "360p"

    return f"{height}p"


def _coerce_positive_int(value) -> Optional[int]:
    try:
        number = int(float(value))
    except Exception:
        return None

    return number if number > 0 else None


def _format_size_mb(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def _size_from_format_group(items) -> Optional[int]:
    if not isinstance(items, list):
        return None

    total = 0
    found = False

    for item in items:
        if not isinstance(item, dict):
            continue

        size = _coerce_positive_int(item.get("filesize") or item.get("filesize_approx"))

        if size:
            total += size
            found = True

    return total if found else None


def _selected_item_size(info: dict) -> Optional[int]:
    requested_downloads_size = _size_from_format_group(info.get("requested_downloads"))

    if requested_downloads_size:
        return requested_downloads_size

    requested_formats_size = _size_from_format_group(info.get("requested_formats"))

    if requested_formats_size:
        return requested_formats_size

    return _coerce_positive_int(info.get("filesize") or info.get("filesize_approx"))


def _selected_item_sizes(info) -> list[int]:
    if not isinstance(info, dict):
        return []

    entries = info.get("entries")

    if isinstance(entries, list) and entries:
        sizes: list[int] = []

        for entry in entries:
            sizes.extend(_selected_item_sizes(entry))

        return sizes

    size = _selected_item_size(info)

    return [size] if size else []


def _raise_if_selected_size_exceeds_limit(info, max_bytes: int) -> None:
    if max_bytes <= 0:
        return

    for size in _selected_item_sizes(info):
        if size > max_bytes:
            raise RuntimeError(
                "file too large before download: "
                f"{_format_size_mb(size)}, limit {_format_size_mb(max_bytes)}"
            )


def _preflight_download_size(
    *,
    ydl: yt_dlp.YoutubeDL,
    url: str,
    max_bytes: int,
) -> None:
    try:
        info = ydl.extract_info(url, download=False)
    except Exception as exc:
        logger.warning("Legacy pre-download size check skipped | url=%s error=%s", url, exc)
        return

    _raise_if_selected_size_exceeds_limit(info, max_bytes)


def estimate_best_single_file_size(info: dict, max_height: int) -> Optional[int]:
    sizes = []

    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue

        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        if not vcodec or vcodec == "none" or not acodec or acodec == "none":
            continue

        height = f.get("height") or 0

        if height and height > max_height:
            continue

        size = f.get("filesize") or f.get("filesize_approx")

        if size:
            sizes.append(int(size))

    return min(sizes) if sizes else None


def choose_youtube_progressive_format(
    info: dict,
    max_height: int,
    max_bytes: int,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    formats = info.get("formats") or []
    candidates = []

    for f in formats:
        if not isinstance(f, dict):
            continue

        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        if not vcodec or vcodec == "none":
            continue

        if not acodec or acodec == "none":
            continue

        height = f.get("height") or 0

        if height and height > max_height:
            continue

        size = f.get("filesize") or f.get("filesize_approx")

        if size and size > max_bytes:
            continue

        format_id = f.get("format_id")

        if not format_id:
            continue

        ext = f.get("ext") or ""
        tbr = f.get("tbr") or 0

        candidates.append(
            (
                0 if ext == "mp4" else 1,
                -(height or 0),
                -tbr,
                format_id,
                height,
                ext,
            )
        )

    if not candidates:
        return None, None, None

    candidates.sort()

    _, _, _, format_id, height, ext = candidates[0]

    return format_id, height, ext


def clean_output_dir(output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for item in output_path.iterdir():
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            pass


def run_yt_dlp_download(
    settings: Settings,
    url: str,
    output_dir: str | Path,
    fmt: str,
    *,
    merge: bool = False,
    platform_auth_slot: int | None = None,
) -> tuple[Optional[Path], Optional[dict], str]:
    clean_output_dir(output_dir)

    output_template = str(Path(output_dir) / "video.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": fmt,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "http_chunk_size": 10 * 1024 * 1024,
    }

    ydl_opts = apply_platform_cookies(settings, url, ydl_opts, platform_auth_slot=platform_auth_slot)

    if merge:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        max_file_size = settings.max_file_size_mb * 1024 * 1024

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            _preflight_download_size(
                ydl=ydl,
                url=url,
                max_bytes=max_file_size,
            )
            downloaded_info = ydl.extract_info(url, download=True)

            if isinstance(downloaded_info, dict) and "entries" in downloaded_info and downloaded_info["entries"]:
                downloaded_info = downloaded_info["entries"][0]

            if isinstance(downloaded_info, dict):
                downloaded_info["_platform_auth_name"] = ydl_opts.get("_platform_auth_name")
                downloaded_info["_platform_auth_slot"] = ydl_opts.get("_platform_auth_slot")

        files = [
            f for f in Path(output_dir).iterdir()
            if f.is_file() and not f.name.endswith(".part")
        ]

        if not files:
            return None, None, f"format {fmt}: файл не найден"

        file_path = max(files, key=lambda p: p.stat().st_size)
        if file_path.stat().st_size > max_file_size:
            return None, None, (
                f"format {fmt}: файл слишком большой "
                f"({file_path.stat().st_size / 1024 / 1024:.1f} MB). "
                f"Лимит сейчас: {settings.max_file_size_mb} MB."
            )

        return file_path, downloaded_info, "ok"

    except Exception as e:
        return None, None, f"format {fmt}: {e}"


def download_fast_single_file(
    settings: Settings,
    url: str,
    output_dir: str | Path,
    info: dict,
    requested_quality: Optional[int],
    platform_auth_slot: int | None = None,
) -> tuple[Optional[Path], Optional[dict], str]:
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()

    if "youtube" in extractor:
        quality = requested_quality or 720
        max_file_size = settings.max_file_size_mb * 1024 * 1024

        format_id, actual_height, ext = choose_youtube_progressive_format(
            info=info,
            max_height=quality,
            max_bytes=max_file_size,
        )

        if not format_id:
            return None, None, "fast: нет подходящего single-file формата"

        file_path, downloaded_info, result = run_yt_dlp_download(
            settings,
            url,
            output_dir,
            format_id,
            merge=False,
            platform_auth_slot=platform_auth_slot,
        )

        if downloaded_info:
            downloaded_info["_download_mode"] = "fast_single_file"
            downloaded_info["_actual_height"] = actual_height

        return file_path, downloaded_info, result

    attempts = [
        "best[height<=720][ext=mp4][vcodec!=none][acodec!=none]/best[height<=720][vcodec!=none][acodec!=none]",
        "best[ext=mp4][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]",
        "best",
    ]

    last_error = "fast: unknown error"

    for fmt in attempts:
        file_path, downloaded_info, result = run_yt_dlp_download(
            settings,
            url,
            output_dir,
            fmt,
            merge=False,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            downloaded_info["_download_mode"] = "fast_single_file"
            downloaded_info["_actual_height"] = downloaded_info.get("height")
            return file_path, downloaded_info, "ok"

        last_error = result

    return None, None, last_error


def download_big_optimized(
    settings: Settings,
    url: str,
    output_dir: str | Path,
    info: dict,
    requested_quality: Optional[int],
    requested_audio_lang: Optional[str] = None,
    platform_auth_slot: int | None = None,
) -> tuple[Optional[Path], Optional[dict], str]:
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    quality = requested_quality or 720

    audio_lang = normalize_audio_lang(requested_audio_lang)
    strict_audio = audio_lang in SUPPORTED_YOUTUBE_AUDIO_LANGS

    if "youtube" in extractor:
        debug_dump_youtube_formats(info, requested_audio_lang)

        max_file_size = settings.max_file_size_mb * 1024 * 1024

        if quality >= 1080:
            qualities = [1080, 720, 480, 360]
        else:
            qualities = [720, 480, 360]

        attempts = []

        # 1. Сначала готовые форматы с нужным языком.
        progressive_candidates = get_exact_progressive_format_ids_for_lang(
            info=info,
            lang_code=requested_audio_lang,
            max_height=quality,
            max_bytes=max_file_size,
        )

        for progressive_id in progressive_candidates:
            attempts.append(progressive_id)

        # 2. Потом старый merge-режим.
        audio_candidates = build_youtube_audio_format_candidates_from_info(
            info,
            requested_audio_lang,
        )

        for q in qualities:
            for audio_fmt in audio_candidates:
                attempts.append(f"bestvideo[height<={q}][ext=mp4][vcodec^=avc1]+{audio_fmt}")
                attempts.append(f"bestvideo[height<={q}][ext=mp4]+{audio_fmt}")
                attempts.append(f"bestvideo[height<={q}]+{audio_fmt}")

            if not strict_audio:
                attempts.extend([
                    f"best[height<={q}][ext=mp4]/best[height<={q}]",
                ])
    else:
        attempts = [
            "best[height<=720][ext=mp4]/best[height<=720]/best",
            "best[height<=480][ext=mp4]/best[height<=480]/best",
            "best[height<=360][ext=mp4]/best[height<=360]/best",
            "worst[ext=mp4]/worst",
        ]

    last_error = "big: unknown error"

    seen = set()
    unique_attempts = []

    for fmt in attempts:
        if fmt in seen:
            continue

        seen.add(fmt)
        unique_attempts.append(fmt)

    for fmt in unique_attempts:
        merge = "+" in fmt

        logger.info(
            "Legacy YouTube attempt | audio=%s strict=%s fmt=%s merge=%s",
            audio_lang,
            strict_audio,
            fmt,
            merge,
        )

        file_path, downloaded_info, result = run_yt_dlp_download(
            settings,
            url,
            output_dir,
            fmt,
            merge=merge,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            downloaded_info["_download_mode"] = "big_optimized_merge" if merge else "big_optimized_single"
            downloaded_info["_actual_height"] = downloaded_info.get("height")
            return file_path, downloaded_info, "ok"

        last_error = result

    return None, None, last_error

def _quality_side(f: dict) -> int:
    """
    Для обычного видео качество обычно height.
    Для Shorts 1080x1920 height=1920, но качество = 1080 по короткой стороне.
    """
    width = f.get("width") or 0
    height = f.get("height") or 0

    try:
        width = int(width or 0)
    except Exception:
        width = 0

    try:
        height = int(height or 0)
    except Exception:
        height = 0

    if width and height:
        return min(width, height)

    return height or width or 0

def download_youtube_hq(
    settings: Settings,
    url: str,
    output_dir: str | Path,
    info: dict,
    max_height: int = 1080,
    requested_audio_lang: Optional[str] = None,
    platform_auth_slot: int | None = None,
) -> tuple[Optional[Path], Optional[dict], str]:
    audio_lang = normalize_audio_lang(requested_audio_lang)
    strict_audio = audio_lang in SUPPORTED_YOUTUBE_AUDIO_LANGS

    debug_dump_youtube_formats(info, requested_audio_lang)

    max_file_size = settings.max_file_size_mb * 1024 * 1024

    progressive_candidates = get_exact_progressive_format_ids_for_lang(
        info=info,
        lang_code=requested_audio_lang,
        max_height=max_height,
        max_bytes=max_file_size,
    )

    audio_candidates = build_youtube_audio_format_candidates_from_info(
        info,
        requested_audio_lang,
    )

    heights = [max_height, 720, 480, 360]
    attempts = []

    # 1. Сначала готовые MP4/Web formats с нужной озвучкой.
    # Для Shorts это как раз 96-17 / 95-17 / 94-17 / 93-17.
    for progressive_id in progressive_candidates:
        attempts.append(progressive_id)

    # 2. Потом пробуем video-only + audio-only.
    for q in heights:
        for audio_fmt in audio_candidates:
            attempts.append(f"bestvideo[height<={q}][ext=mp4][vcodec^=avc1]+{audio_fmt}")
            attempts.append(f"bestvideo[height<={q}][ext=mp4]+{audio_fmt}")
            attempts.append(f"bestvideo[height<={q}]+{audio_fmt}")

    # 3. Fallback без языка только для Original.
    if not strict_audio:
        attempts.extend([
            f"best[height<={max_height}][ext=mp4][vcodec^=avc1]",
            f"best[height<={max_height}][ext=mp4]",
            f"best[height<={max_height}]/best",
        ])

    last_error = "youtube_hq: unknown error"

    seen = set()
    unique_attempts = []

    for fmt in attempts:
        if fmt in seen:
            continue

        seen.add(fmt)
        unique_attempts.append(fmt)

    for fmt in unique_attempts:
        merge = "+" in fmt

        logger.info(
            "Legacy YouTube HQ attempt | audio=%s strict=%s fmt=%s merge=%s",
            audio_lang,
            strict_audio,
            fmt,
            merge,
        )

        file_path, downloaded_info, result = run_yt_dlp_download(
            settings=settings,
            url=url,
            output_dir=output_dir,
            fmt=fmt,
            merge=merge,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            downloaded_info["_download_mode"] = "youtube_hq_single" if not merge else "youtube_hq_h264"
            downloaded_info["_actual_height"] = _quality_side(downloaded_info) or max_height
            return file_path, downloaded_info, "ok"

        last_error = result

    return None, None, last_error

def download_video_smart_legacy(
    settings: Settings,
    url: str,
    output_dir: str | Path,
    info: dict,
    requested_quality: Optional[int] = None,
    requested_audio_lang: Optional[str] = None,
    platform_auth_slot: int | None = None,
) -> tuple[Optional[Path], Optional[dict], str]:
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    quality = 1080 if requested_quality == 1081 else (requested_quality or 720)
    is_hq = requested_quality == 1081

    if "youtube" in extractor and is_hq:
        file_path, downloaded_info, result = download_youtube_hq(
            settings=settings,
            url=url,
            output_dir=output_dir,
            info=info,
            max_height=1080,
            requested_audio_lang=requested_audio_lang,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            return file_path, downloaded_info, result

    estimated = estimate_best_single_file_size(info, quality)
    fast_mode_max_size = settings.fast_mode_max_mb * 1024 * 1024
    max_file_size = settings.max_file_size_mb * 1024 * 1024

    should_try_fast_first = True

    if estimated and estimated > fast_mode_max_size:
        should_try_fast_first = False

    if "youtube" in extractor and requested_audio_lang and requested_audio_lang != "auto":
        should_try_fast_first = False

    # оставляем как в старом боте
    if "youtube" in extractor and quality >= 1080:
        progressive_id, _, _ = choose_youtube_progressive_format(info, quality, max_file_size)
        should_try_fast_first = bool(progressive_id)

    errors = []

    if should_try_fast_first:
        file_path, downloaded_info, result = download_fast_single_file(
            settings,
            url,
            output_dir,
            info,
            requested_quality,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            return file_path, downloaded_info, result

        errors.append(result)

    file_path, downloaded_info, result = download_big_optimized(
        settings,
        url,
        output_dir,
        info,
        requested_quality,
        requested_audio_lang,
        platform_auth_slot=platform_auth_slot,
    )

    if file_path and downloaded_info:
        return file_path, downloaded_info, result

    errors.append(result)

    if not should_try_fast_first:
        file_path, downloaded_info, result = download_fast_single_file(
            settings,
            url,
            output_dir,
            info,
            requested_quality,
            platform_auth_slot=platform_auth_slot,
        )

        if file_path and downloaded_info:
            return file_path, downloaded_info, result

        errors.append(result)

    return None, None, " | ".join([e for e in errors if e])[-1500:]


def legacy_cache_key(
    info: dict,
    url: str,
    requested_quality: Optional[int],
    requested_audio_lang: Optional[str],
) -> str:
    extractor = info.get("extractor_key") or info.get("extractor") or "unknown"
    video_id = info.get("id")

    if video_id:
        base = f"{extractor}:{video_id}"
    else:
        base = "url:" + hashlib.sha256(url.strip().encode("utf-8")).hexdigest()

    quality_part = requested_quality if requested_quality else "auto"
    lang_part = normalize_audio_lang(requested_audio_lang) or "auto"

    return f"{base}:q{quality_part}:a{lang_part}"

def debug_dump_youtube_formats(info: dict, requested_audio_lang: Optional[str] = None) -> None:
    """
    Печатает в лог все форматы YouTube.
    Нужно, чтобы увидеть реальные format_id русской/английской дорожки.
    """
    video_id = info.get("id")
    title = info.get("title")

    logger.info(
        "YouTube formats dump | id=%s title=%s requested_audio=%s",
        video_id,
        title,
        requested_audio_lang,
    )

    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue

        logger.info(
            "YT_FMT | id=%s ext=%s height=%s vcodec=%s acodec=%s lang=%s abr=%s tbr=%s note=%s format=%s",
            f.get("format_id"),
            f.get("ext"),
            f.get("height"),
            f.get("vcodec"),
            f.get("acodec"),
            f.get("language"),
            f.get("abr"),
            f.get("tbr"),
            f.get("format_note"),
            f.get("format"),
        )


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _score_audio_format(f: dict) -> tuple:
    ext = str(f.get("ext") or "").lower()
    acodec = str(f.get("acodec") or "").lower()

    return (
        1 if ext == "m4a" else 0,
        1 if "mp4a" in acodec else 0,
        _safe_float(f.get("abr")),
        _safe_float(f.get("tbr")),
    )


def _score_progressive_format(f: dict) -> tuple:
    ext = str(f.get("ext") or "").lower()
    vcodec = str(f.get("vcodec") or "").lower()

    return (
        _quality_side(f),
        1 if ext == "mp4" else 0,
        1 if vcodec.startswith("avc1") else 0,
        _safe_float(f.get("tbr")),
    )


def get_exact_audio_format_ids_for_lang(info: dict, lang_code: Optional[str]) -> list[str]:
    """
    Ищем audio-only format_id для конкретного языка.
    Это лучше, чем bestaudio[language=ru], потому что берём точный ID.
    """
    lang_code = normalize_audio_lang(lang_code)

    if lang_code not in SUPPORTED_YOUTUBE_AUDIO_LANGS:
        return []

    candidates = []

    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue

        format_id = f.get("format_id")
        if not format_id:
            continue

        acodec = f.get("acodec")
        vcodec = f.get("vcodec")

        if not acodec or acodec == "none":
            continue

        # audio-only
        if vcodec and vcodec != "none":
            continue

        lang = normalize_audio_lang(f.get("language"))

        if lang != lang_code:
            continue

        candidates.append(f)

    candidates.sort(key=_score_audio_format, reverse=True)

    return [str(f["format_id"]) for f in candidates]


def get_exact_progressive_format_ids_for_lang(
    info: dict,
    lang_code: Optional[str],
    max_height: int,
    max_bytes: int,
) -> list[str]:
    """
    Ищем готовые video+audio format_id для конкретного языка.
    Для Shorts качество считаем по короткой стороне: 1080x1920 = 1080p.
    """
    lang_code = normalize_audio_lang(lang_code)

    if lang_code not in SUPPORTED_YOUTUBE_AUDIO_LANGS:
        return []

    candidates = []

    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue

        format_id = f.get("format_id")
        if not format_id:
            continue

        acodec = f.get("acodec")
        vcodec = f.get("vcodec")

        if not acodec or acodec == "none":
            continue

        if not vcodec or vcodec == "none":
            continue

        lang = normalize_audio_lang(f.get("language"))

        if lang != lang_code:
            continue

        quality_side = _quality_side(f)

        if quality_side and quality_side > max_height:
            continue

        size = f.get("filesize") or f.get("filesize_approx")

        if size and int(size) > max_bytes:
            continue

        candidates.append(f)

    candidates.sort(key=_score_progressive_format, reverse=True)

    result = [str(f["format_id"]) for f in candidates]

    logger.info(
        "Exact progressive formats for lang=%s max_height=%s -> %s",
        lang_code,
        max_height,
        result,
    )

    return result


def build_youtube_audio_format_candidates_from_info(
    info: dict,
    audio_lang: Optional[str],
) -> list[str]:
    """
    Новый порядок:
    1. Точные audio format_id из metadata.
    2. Старые bestaudio[language=...] фильтры.
    """
    audio_lang = normalize_audio_lang(audio_lang)

    if audio_lang not in ("ru", "en"):
        return build_youtube_audio_format_candidates(audio_lang)

    exact_ids = get_exact_audio_format_ids_for_lang(info, audio_lang)

    old_candidates = build_youtube_audio_format_candidates(audio_lang)

    result = []

    for fmt in exact_ids + old_candidates:
        if fmt not in result:
            result.append(fmt)

    return result
