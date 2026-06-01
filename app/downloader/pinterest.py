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


def is_pinterest_url(url: str | None) -> bool:
    if not url:
        return False

    value = str(url).lower()

    return (
        "pinterest.com" in value
        or "pin.it" in value
    )


def _natural_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.name.lower())
    result = []

    for part in parts:
        result.append(int(part) if part.isdigit() else part)

    return result


def _collect_downloaded_media(output_dir: Path) -> list[Path]:
    files = []

    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue

        if path.name.endswith(".part"):
            continue

        if path.suffix.lower() not in PHOTO_SUFFIXES | VIDEO_SUFFIXES:
            continue

        files.append(path)

    files.sort(key=_natural_key)
    return files


def download_pinterest_pin(
    *,
    settings: Settings,
    url: str,
    output_dir: Path,
    platform_auth_slot: int | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = get_cookie_path(settings, "pinterest", platform_auth_slot=platform_auth_slot)

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
        "Pinterest gallery-dl started | url=%s output_dir=%s cookies=%s",
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
        "Pinterest gallery-dl finished | code=%s stdout=%s stderr=%s",
        result.returncode,
        (result.stdout or "")[-1500:],
        (result.stderr or "")[-1500:],
    )

    files = _collect_downloaded_media(output_dir)

    if files:
        logger.info(
            "Pinterest files collected | count=%s files=%s",
            len(files),
            [path.name for path in files],
        )
        return files

    raise RuntimeError(
        "gallery-dl did not create Pinterest files"
        + (f": {(result.stderr or result.stdout)[-1000:]}" if (result.stderr or result.stdout) else "")
    )
