import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from app.config import Settings

import json

from app.downloader.cookies import get_cookie_path, get_platform_proxy_url

logger = logging.getLogger(__name__)


PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_SUFFIXES = {".m4a", ".mp3", ".aac", ".opus", ".ogg"}

LIVE_PHOTO_MAX_VIDEO_SECONDS = 10.0
LIVE_PHOTO_MAX_VIDEO_BYTES = 10 * 1024 * 1024

def is_tiktok_photo_url(url: str | None) -> bool:
    if not url:
        return False

    url = str(url).lower()

    return "/photo/" in url or "/share/photo/" in url


def is_tiktok_music_url(url: str | None) -> bool:
    if not url:
        return False

    url = str(url).lower()

    return "/music/" in url


def _natural_key(path: Path) -> list:
    """
    Чтобы файлы шли 1,2,3,10, а не 1,10,2.
    """
    parts = re.split(r"(\d+)", path.name.lower())

    result = []

    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part)

    return result


def _get_tiktok_cookies_path(settings: Settings, platform_auth_slot: int | None = None) -> Path | None:
    return get_cookie_path(settings, "tiktok", platform_auth_slot=platform_auth_slot)


def _collect_downloaded_media(output_dir: Path) -> list[Path]:
    files: list[Path] = []

    allowed_suffixes = PHOTO_SUFFIXES | VIDEO_SUFFIXES | AUDIO_SUFFIXES

    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue

        if path.name.endswith(".part"):
            continue

        if path.suffix.lower() not in allowed_suffixes:
            continue

        # gallery-dl может скачать аватарки/metadata thumbnails.
        # На первом этапе оставляем все медиа, но сортируем.
        files.append(path)

    files.sort(key=_natural_key)

    return files

def _probe_video_info(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration,size",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
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
            logger.warning(
                "TikTok live probe failed | file=%s | stderr=%s",
                path,
                result.stderr[-1000:],
            )
            return {}

        data = json.loads(result.stdout or "{}")
        fmt = data.get("format") or {}
        streams = data.get("streams") or []
        stream = streams[0] if streams else {}

        try:
            duration = float(fmt.get("duration") or 0)
        except Exception:
            duration = 0.0

        try:
            size = int(fmt.get("size") or path.stat().st_size)
        except Exception:
            size = path.stat().st_size

        return {
            "duration": duration,
            "size": size,
            "codec": stream.get("codec_name"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "avg_frame_rate": stream.get("avg_frame_rate"),
            "r_frame_rate": stream.get("r_frame_rate"),
        }

    except Exception as e:
        logger.warning("TikTok live probe crashed | file=%s | error=%s", path, e)
        return {}


def _normalized_live_key(path: Path) -> str:
    stem = path.stem.lower()

    # Убираем типичные хвосты, если gallery-dl назовёт пары похоже:
    # 001.jpg / 001.mp4
    # 001_cover.jpg / 001_video.mp4
    for marker in [
        "_cover",
        "-cover",
        "_thumb",
        "-thumb",
        "_thumbnail",
        "-thumbnail",
        "_image",
        "-image",
        "_photo",
        "-photo",
        "_video",
        "-video",
        "_live",
        "-live",
    ]:
        stem = stem.replace(marker, "")

    stem = re.sub(r"\s+", "_", stem)
    return stem


def _is_live_video_candidate(path: Path, info: dict) -> bool:
    duration = float(info.get("duration") or 0)
    size = int(info.get("size") or path.stat().st_size)

    if duration <= 0:
        return False

    if duration > LIVE_PHOTO_MAX_VIDEO_SECONDS:
        return False

    if size > LIVE_PHOTO_MAX_VIDEO_BYTES:
        return False

    return True


def analyze_tiktok_live_photo_files(files: list[Path]) -> dict:
    photos = [
        path for path in files
        if path.suffix.lower() in PHOTO_SUFFIXES
    ]

    videos = [
        path for path in files
        if path.suffix.lower() in VIDEO_SUFFIXES
    ]

    audios = [
        path for path in files
        if path.suffix.lower() in AUDIO_SUFFIXES
    ]

    photo_by_key: dict[str, Path] = {}

    for photo in photos:
        key = _normalized_live_key(photo)
        photo_by_key[key] = photo

    live_candidates = []
    sidecar_videos: set[Path] = set()

    video_infos: dict[Path, dict] = {}

    for video in videos:
        info = _probe_video_info(video)
        video_infos[video] = info

        if not _is_live_video_candidate(video, info):
            continue

        video_key = _normalized_live_key(video)
        paired_photo = photo_by_key.get(video_key)

        if paired_photo:
            live_candidates.append(
                {
                    "photo": paired_photo,
                    "video": video,
                    "reason": "same_stem",
                    "video_info": info,
                }
            )
            sidecar_videos.add(video)

    # Fallback: если количество фото и коротких видео совпадает,
    # пробуем считать их парами по порядку.
    if not live_candidates and photos and videos and len(photos) == len(videos):
        sorted_photos = sorted(photos, key=_natural_key)
        sorted_videos = sorted(videos, key=_natural_key)

        for photo, video in zip(sorted_photos, sorted_videos):
            info = video_infos.get(video) or _probe_video_info(video)

            if not _is_live_video_candidate(video, info):
                continue

            live_candidates.append(
                {
                    "photo": photo,
                    "video": video,
                    "reason": "same_count_order",
                    "video_info": info,
                }
            )
            sidecar_videos.add(video)

    logger.info(
        "TikTok live photo diagnostics | photos=%s videos=%s audios=%s live_candidates=%s sidecar_videos=%s",
        len(photos),
        len(videos),
        len(audios),
        len(live_candidates),
        [path.name for path in sidecar_videos],
    )

    for candidate in live_candidates:
        logger.info(
            "TikTok live candidate | reason=%s photo=%s video=%s info=%s",
            candidate.get("reason"),
            candidate.get("photo").name if candidate.get("photo") else None,
            candidate.get("video").name if candidate.get("video") else None,
            candidate.get("video_info"),
        )

    return {
        "photos": photos,
        "videos": videos,
        "audios": audios,
        "live_candidates": live_candidates,
        "sidecar_videos": sidecar_videos,
    }

def _run_gallery_dl(
    settings: Settings,
    url: str,
    output_dir: Path,
    *,
    platform_auth_slot: int | None = None,
    proxy_url: str | None = None,
) -> tuple[int, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = _get_tiktok_cookies_path(settings, platform_auth_slot)
    selected_proxy_url = get_platform_proxy_url(
        settings,
        "tiktok",
        proxy_url_override=proxy_url,
    )

    cmd = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--no-part",
        "-d",
        str(output_dir),
    ]

    if cookies_path:
        cmd.extend(["--cookies", str(cookies_path)])

    if selected_proxy_url:
        cmd.extend(["--proxy", selected_proxy_url])

    # Немного меньше мусора от gallery-dl.
    # Если надо будет дебажить, временно поменяем на "--verbose".
    cmd.append(url)

    logger.info(
        "TikTok photo gallery-dl started | url=%s output_dir=%s cookies=%s proxy=%s",
        url,
        output_dir,
        cookies_path,
        bool(selected_proxy_url),
    )

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )

    logger.info(
        "TikTok photo gallery-dl finished | code=%s stdout=%s stderr=%s",
        result.returncode,
        (result.stdout or "")[-1500:],
        (result.stderr or "")[-1500:],
    )

    return result.returncode, result.stdout or "", result.stderr or ""


def download_tiktok_photo_post(
    *,
    settings: Settings,
    url: str,
    output_dir: Path,
    platform_auth_slot: int | None = None,
    proxy_url: str | None = None,
) -> list[Path]:
    """
    Скачивает TikTok photo/slideshow через gallery-dl.

    Возвращает список файлов:
    - фото,
    - иногда видео/live-like элементы,
    - иногда аудио, если extractor его достал.

    На первом этапе в download_engine мы отправим только фото/видео.
    Аудио отдельно подключим позже, если будет нужно.
    """
    code, stdout, stderr = _run_gallery_dl(
        settings=settings,
        url=url,
        output_dir=output_dir,
        platform_auth_slot=platform_auth_slot,
        proxy_url=proxy_url,
    )

    files = _collect_downloaded_media(output_dir)

    if files:
        diagnostics = analyze_tiktok_live_photo_files(files)
        sidecar_videos = diagnostics.get("sidecar_videos") or set()

        # Пока Telegram live photo не отправляем.
        # Если нашли live-sidecar mp4, не отправляем его дублем рядом с фото.
        files_to_send = [
            path for path in files
            if path not in sidecar_videos
        ]

        logger.info(
            "TikTok photo files collected | total=%s send=%s files=%s skipped_live_sidecars=%s",
            len(files),
            len(files_to_send),
            [str(path.name) for path in files_to_send],
            [str(path.name) for path in sidecar_videos],
        )

        return files_to_send

    error_text = "\n".join([stdout, stderr]).strip()

    raise RuntimeError(
        "gallery-dl did not create TikTok photo files"
        + (f": {error_text[-1000:]}" if error_text else "")
    )
