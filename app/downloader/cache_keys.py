import hashlib
import re
from urllib.parse import urlparse

from app.downloader.content_types import DownloadAction, Platform


def _sha256_short(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _clean(value: str | None) -> str:
    if not value:
        return ""

    value = str(value).strip().lower()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_.:-]+", "_", value)

    return value.strip("_")


def _path_parts(url: str) -> list[str]:
    path = urlparse(url).path.strip("/")
    return [part for part in path.split("/") if part]


def extract_source_id(platform: Platform, original_url: str, resolved_url: str | None = None) -> str:
    url = resolved_url or original_url
    parts = _path_parts(url)

    if platform == Platform.YOUTUBE:
        parsed = urlparse(url)

        if "youtu.be" in parsed.netloc and parts:
            return parts[0]

        if "/shorts/" in parsed.path and "shorts" in parts:
            index = parts.index("shorts")
            if len(parts) > index + 1:
                return parts[index + 1]

        query = parsed.query
        for item in query.split("&"):
            if item.startswith("v="):
                return item.replace("v=", "", 1)

        if "source" in parts:
            index = parts.index("source")
            if len(parts) > index + 1:
                return f"source:{parts[index + 1]}"

    if platform == Platform.TIKTOK:
        for marker in ("video", "photo", "music"):
            if marker in parts:
                index = parts.index(marker)
                if len(parts) > index + 1:
                    return f"{marker}:{parts[index + 1]}"

    if platform == Platform.INSTAGRAM:
        for marker in ("p", "reel", "reels", "stories", "audio"):
            if marker in parts:
                index = parts.index(marker)
                if len(parts) > index + 1:
                    if marker == "stories" and len(parts) > index + 2:
                        return f"story:{parts[index + 1]}:{parts[index + 2]}"
                    return f"{marker}:{parts[index + 1]}"

    if platform == Platform.PINTEREST:
        if "pin" in parts:
            index = parts.index("pin")
            if len(parts) > index + 1:
                return f"pin:{parts[index + 1]}"

        if "pin.it" in urlparse(url).netloc and parts:
            return f"pin_short:{parts[0]}"

    return "url:" + _sha256_short(url)


def build_source_key(platform: Platform, original_url: str, resolved_url: str | None = None) -> str:
    source_id = extract_source_id(platform, original_url, resolved_url)
    return f"{platform.value}:{_clean(source_id)}"


def build_variant_key(
    *,
    action: DownloadAction,
    quality: int | None = None,
    audio_lang: str | None = None,
    media_type: str | None = None,
) -> str:
    parts = [action.value]

    if quality:
        parts.append(f"q{quality}")

    if audio_lang:
        parts.append(f"a{_clean(audio_lang)}")

    if media_type:
        parts.append(f"m{_clean(media_type)}")

    return ":".join(parts)


def build_bundle_key(source_key: str, variant_key: str) -> str:
    return f"{source_key}|{variant_key}"


def build_cache_key(bundle_key: str, item_index: int = 0) -> str:
    return f"{bundle_key}|i{item_index}"