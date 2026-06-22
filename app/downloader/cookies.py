from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.db.cookie_auth_repo import get_auth_slot, normalize_cookie_platform


def _normalize_cookie_path(settings: Settings, value, *, require_existing: bool = True) -> Path | None:
    if not value:
        return None

    base_dir = getattr(settings, "base_dir", None)
    base_dir = Path(base_dir) if base_dir else Path.cwd()

    path = Path(value)

    if not path.is_absolute():
        path = base_dir / path

    if not require_existing:
        return path

    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return path

    return None


def detect_cookie_platform(url: str | None) -> str | None:
    if not url:
        return None

    host = urlparse(str(url)).netloc.lower()

    if host == "youtu.be" or host.endswith("youtube.com"):
        return "youtube"

    if host.endswith("instagram.com"):
        return "instagram"

    if host.endswith("tiktok.com") or host == "vt.tiktok.com":
        return "tiktok"

    if host.endswith("pinterest.com") or host == "pin.it":
        return "pinterest"

    return None


def _slot_paths_for_platform(settings: Settings, platform: str):
    platform = normalize_cookie_platform(platform)

    if platform == "youtube":
        return getattr(settings, "youtube_cookie_slot_paths", (None, None, None, None))

    if platform == "instagram":
        return getattr(settings, "instagram_cookie_slot_paths", (None, None, None, None))

    if platform == "tiktok":
        return getattr(settings, "tiktok_cookie_slot_paths", (None, None, None, None))

    if platform == "pinterest":
        return getattr(settings, "pinterest_cookie_slot_paths", (None, None, None, None))

    return (None, None, None, None)


def get_cookie_slot_path(
    settings: Settings,
    platform: str,
    slot: int,
    *,
    require_existing: bool = True,
) -> Path | None:
    platform = normalize_cookie_platform(platform)

    if not platform or slot <= 0:
        return None

    paths = _slot_paths_for_platform(settings, platform)

    if slot >= len(paths):
        return None

    return _normalize_cookie_path(settings, paths[slot], require_existing=require_existing)


def get_cookie_path(
    settings: Settings,
    platform: str,
    *,
    platform_auth_slot: int | None = None,
) -> Path | None:
    platform = normalize_cookie_platform(platform)

    if not platform:
        return None

    slot = get_auth_slot(settings, platform) if platform_auth_slot is None else int(platform_auth_slot)

    if slot == 0:
        return None

    return get_cookie_slot_path(settings, platform, slot, require_existing=True)


def is_cookie_slot_usable(settings: Settings, platform: str, slot: int) -> bool:
    if slot == 0:
        return True

    path = get_cookie_slot_path(settings, platform, slot, require_existing=True)
    return bool(path)


def get_auth_name(platform: str, slot: int) -> str:
    platform = normalize_cookie_platform(platform) or str(platform or "unknown")

    if slot == 0:
        return "guest"

    return f"{platform}_cookies_{slot}"


def get_platform_proxy_url(
    settings: Settings,
    platform: str | None,
    *,
    proxy_url_override: str | None = None,
) -> str:
    if proxy_url_override is not None:
        return str(proxy_url_override or "").strip()

    platform = normalize_cookie_platform(platform) or str(platform or "").lower().strip()
    attr_name = {
        "youtube": "youtube_proxy_url",
        "instagram": "instagram_proxy_url",
        "tiktok": "tiktok_proxy_url",
        "pinterest": "pinterest_proxy_url",
    }.get(platform)

    if not attr_name:
        return ""

    return str(getattr(settings, attr_name, "") or "").strip()


def apply_platform_cookies(
    settings: Settings,
    url: str,
    ydl_opts: dict,
    *,
    platform_auth_slot: int | None = None,
    proxy_url_override: str | None = None,
) -> dict:
    platform = detect_cookie_platform(url)

    if not platform:
        return ydl_opts

    slot = get_auth_slot(settings, platform) if platform_auth_slot is None else int(platform_auth_slot)
    cookie_path = get_cookie_path(settings, platform, platform_auth_slot=slot)

    if cookie_path:
        ydl_opts["cookiefile"] = str(cookie_path)

    ydl_opts["_platform_auth_name"] = get_auth_name(platform, slot)
    ydl_opts["_platform_auth_slot"] = slot

    proxy_url = get_platform_proxy_url(
        settings,
        platform,
        proxy_url_override=proxy_url_override,
    )
    if proxy_url:
        ydl_opts["proxy"] = proxy_url

    # YouTube and YouTube Music share slots and both need challenge support.
    if platform == "youtube":
        deno_path = (
            getattr(settings, "deno_path", None)
            or getattr(settings, "DENO_PATH", None)
        )

        ydl_opts["remote_components"] = ["ejs:github"]

        if deno_path and Path(deno_path).exists():
            ydl_opts["js_runtimes"] = {
                "deno": {
                    "path": str(deno_path),
                }
            }

    return ydl_opts
