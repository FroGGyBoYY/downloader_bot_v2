import re
from urllib.parse import urlparse

from app.config import Settings
from app.models import DetectedLink


URL_RE = re.compile(r"https?://\S+")


PLATFORM_TITLES = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "pinterest": "Pinterest",
}


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")

    if not match:
        return None

    return match.group(0).strip(" <>[]()\"'")


def normalize_host(host: str) -> str:
    host = host.lower().strip()

    for prefix in ("www.", "m.", "vm."):
        if host.startswith(prefix):
            host = host[len(prefix):]

    return host


def detect_platform(url: str, settings: Settings) -> DetectedLink | None:
    try:
        parsed = urlparse(url)
        host = normalize_host(parsed.netloc)
    except Exception:
        return None

    if not host:
        return None

    allowed = any(host == domain or host.endswith("." + domain) for domain in settings.allowed_domains)

    if not allowed:
        return None

    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        return DetectedLink(url=url.strip(), platform="youtube", host=host)

    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return DetectedLink(url=url.strip(), platform="tiktok", host=host)

    if host == "instagram.com" or host.endswith(".instagram.com"):
        return DetectedLink(url=url.strip(), platform="instagram", host=host)

    if host == "pinterest.com" or host.endswith(".pinterest.com") or host == "pin.it":
        return DetectedLink(url=url.strip(), platform="pinterest", host=host)

    return None


def get_platform_title(platform: str) -> str:
    return PLATFORM_TITLES.get(platform, platform)