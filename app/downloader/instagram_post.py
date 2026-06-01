import logging
import re
import subprocess
import sys
from pathlib import Path

from app.config import Settings
from app.downloader.cookies import get_cookie_path

logger = logging.getLogger(__name__)


PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_SUFFIXES = {".m4a", ".mp3", ".aac", ".opus", ".ogg"}


def is_instagram_post_url(url: str | None) -> bool:
    if not url:
        return False

    value = str(url).lower()

    return (
        "instagram.com/p/" in value
        or "www.instagram.com/p/" in value
    )


def is_instagram_reel_url(url: str | None) -> bool:
    if not url:
        return False

    value = str(url).lower()

    return (
        "instagram.com/reel/" in value
        or "www.instagram.com/reel/" in value
    )


def _natural_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.name.lower())

    result = []

    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part)

    return result


def _get_instagram_cookies_path(settings: Settings, platform_auth_slot: int | None = None) -> Path | None:
    return get_cookie_path(settings, "instagram", platform_auth_slot=platform_auth_slot)


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

        files.append(path)

    files.sort(key=_natural_key)

    return files


def _run_gallery_dl(
    settings: Settings,
    url: str,
    output_dir: Path,
    *,
    platform_auth_slot: int | None = None,
) -> tuple[int, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = _get_instagram_cookies_path(settings, platform_auth_slot)

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

    cmd.append(url)

    logger.info(
        "Instagram post gallery-dl started | url=%s output_dir=%s cookies=%s",
        url,
        output_dir,
        cookies_path,
    )

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=240,
    )

    logger.info(
        "Instagram post gallery-dl finished | code=%s stdout=%s stderr=%s",
        result.returncode,
        (result.stdout or "")[-1500:],
        (result.stderr or "")[-1500:],
    )

    return result.returncode, result.stdout or "", result.stderr or ""


def download_instagram_post(
    *,
    settings: Settings,
    url: str,
    output_dir: Path,
    platform_auth_slot: int | None = None,
) -> list[Path]:
    """
    Скачивает Instagram /p/ post или carousel через gallery-dl.

    Возвращает:
    - фото
    - видео
    - аудио, если extractor вдруг скачал отдельный аудиофайл
    """
    code, stdout, stderr = _run_gallery_dl(
        settings=settings,
        url=url,
        output_dir=output_dir,
        platform_auth_slot=platform_auth_slot,
    )

    files = _collect_downloaded_media(output_dir)

    if files:
        logger.info(
            "Instagram post files collected | count=%s files=%s",
            len(files),
            [path.name for path in files],
        )
        return files

    error_text = "\n".join([stdout, stderr]).strip()

    raise RuntimeError(
        "gallery-dl did not create Instagram post files"
        + (f": {error_text[-1000:]}" if error_text else "")
    )
