from dataclasses import dataclass
from typing import Any


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "avif"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "mkv", "m4v"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "opus", "ogg", "wav"}


IGNORE_LIST_KEYS = {
    "formats",
    "thumbnails",
    "thumbnail",
    "display_resources",
    "displayresources",
    "subtitles",
    "automatic_captions",
    "automaticcaptions",
}


KNOWN_MEDIA_LIST_KEYS = {
    "entries",
    "carousel_media",
    "carouselmedia",
    "sidecar",
    "items",
    "slides",
    "images",
    "image_list",
    "imagelist",
    "image_urls",
    "imageurls",
    "photos",
    "photo_list",
    "photolist",
}


@dataclass(frozen=True)
class MediaSummary:
    photo_count: int
    video_count: int
    audio_count: int
    unknown_count: int
    entries_count: int
    detected_from: str

    @property
    def total_media_count(self) -> int:
        return self.photo_count + self.video_count + self.audio_count + self.unknown_count

    @property
    def is_album(self) -> bool:
        return self.photo_count + self.video_count > 1

    @property
    def is_mixed_album(self) -> bool:
        return self.photo_count > 0 and self.video_count > 0

    @property
    def is_photo_album(self) -> bool:
        return self.photo_count > 1 and self.video_count == 0

    @property
    def is_video_album(self) -> bool:
        return self.video_count > 1 and self.photo_count == 0


def _ext_from_url(url: str | None) -> str:
    if not url:
        return ""

    clean = str(url).split("?")[0].split("#")[0]
    if "." not in clean:
        return ""

    return clean.rsplit(".", 1)[-1].lower().strip()


def _formats_have_video(info: dict[str, Any]) -> bool:
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        vcodec = fmt.get("vcodec")
        ext = str(fmt.get("ext") or "").lower()

        if vcodec and vcodec != "none":
            return True

        if ext in VIDEO_EXTENSIONS:
            return True

    return False


def _formats_have_audio_only(info: dict[str, Any]) -> bool:
    has_audio = False
    has_video = False

    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        acodec = fmt.get("acodec")
        vcodec = fmt.get("vcodec")
        ext = str(fmt.get("ext") or "").lower()

        if acodec and acodec != "none":
            has_audio = True

        if vcodec and vcodec != "none":
            has_video = True

        if ext in AUDIO_EXTENSIONS:
            has_audio = True

    return has_audio and not has_video


def detect_item_kind(item: Any) -> str:
    if isinstance(item, str):
        ext = _ext_from_url(item)

        if ext in IMAGE_EXTENSIONS:
            return "photo"

        if ext in VIDEO_EXTENSIONS:
            return "video"

        if ext in AUDIO_EXTENSIONS:
            return "audio"

        return "unknown"

    if not isinstance(item, dict):
        return "unknown"

    ext = str(item.get("ext") or "").lower()
    url_ext = _ext_from_url(item.get("url"))
    duration = item.get("duration")
    vcodec = item.get("vcodec")
    acodec = item.get("acodec")

    if ext in IMAGE_EXTENSIONS or url_ext in IMAGE_EXTENSIONS:
        return "photo"

    if ext in VIDEO_EXTENSIONS or url_ext in VIDEO_EXTENSIONS:
        return "video"

    if ext in AUDIO_EXTENSIONS or url_ext in AUDIO_EXTENSIONS:
        return "audio"

    if vcodec and vcodec != "none":
        return "video"

    if acodec and acodec != "none" and not vcodec:
        return "audio"

    if _formats_have_video(item):
        return "video"

    if _formats_have_audio_only(item):
        return "audio"

    if duration:
        return "video"

    # Часто фото-посты приходят как объект без duration, но с thumbnail/url.
    if item.get("thumbnail") and not duration and not _formats_have_video(item):
        return "photo"

    return "unknown"


def _count_kinds(items: list[Any]) -> dict[str, int]:
    result = {
        "photo": 0,
        "video": 0,
        "audio": 0,
        "unknown": 0,
    }

    for item in items:
        kind = detect_item_kind(item)

        if kind not in result:
            kind = "unknown"

        result[kind] += 1

    return result


def _get_entries(info: dict[str, Any]) -> list[Any]:
    entries = info.get("entries") or []

    if not isinstance(entries, list):
        return []

    return [entry for entry in entries if entry]


def _find_known_media_lists(obj: Any, *, depth: int = 0, max_depth: int = 4) -> list[Any]:
    if depth > max_depth:
        return []

    found: list[Any] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_norm = str(key).lower().replace("_", "")

            if key_norm in IGNORE_LIST_KEYS:
                continue

            if isinstance(value, list) and key_norm in KNOWN_MEDIA_LIST_KEYS:
                # Не считаем thumbnails/formats, но считаем entries/images/slides/carousel.
                found.extend([item for item in value if item])

            elif isinstance(value, dict):
                found.extend(_find_known_media_lists(value, depth=depth + 1, max_depth=max_depth))

            elif isinstance(value, list):
                # Внутрь неизвестных списков не лезем глубоко, чтобы не спутать размеры одного фото с каруселью.
                continue

    return found


def summarize_media(info: dict[str, Any]) -> MediaSummary:
    entries = _get_entries(info)
    entries_count = len(entries)

    if entries_count > 0:
        counts = _count_kinds(entries)

        return MediaSummary(
            photo_count=counts["photo"],
            video_count=counts["video"],
            audio_count=counts["audio"],
            unknown_count=counts["unknown"],
            entries_count=entries_count,
            detected_from="entries",
        )

    known_items = _find_known_media_lists(info)

    if known_items:
        counts = _count_kinds(known_items)

        return MediaSummary(
            photo_count=counts["photo"],
            video_count=counts["video"],
            audio_count=counts["audio"],
            unknown_count=counts["unknown"],
            entries_count=entries_count,
            detected_from="known_media_lists",
        )

    kind = detect_item_kind(info)
    counts = {
        "photo": 0,
        "video": 0,
        "audio": 0,
        "unknown": 0,
    }
    counts[kind] = 1

    return MediaSummary(
        photo_count=counts["photo"],
        video_count=counts["video"],
        audio_count=counts["audio"],
        unknown_count=counts["unknown"],
        entries_count=entries_count,
        detected_from="single_info",
    )