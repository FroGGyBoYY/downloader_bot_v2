from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.downloader.content_types import ContentType, DownloadAction, Platform


@dataclass(frozen=True)
class UrlRouteHint:
    platform: Platform
    content_type: ContentType
    action: DownloadAction
    routing_url: str
    confidence: float
    reason: str


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def _path(url: str) -> str:
    return urlparse(url).path.lower()


def _contains_any_path(urls: list[str], pattern: str) -> bool:
    return any(pattern in _path(url) for url in urls if url)


def _host_contains_any(urls: list[str], text: str) -> bool:
    return any(text in _host(url) for url in urls if url)


def _is_youtube_music_playlist_url(url: str) -> bool:
    parsed = urlparse(url)

    if "music.youtube.com" not in parsed.netloc.lower():
        return False

    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if path.startswith("/playlist"):
        return bool(query.get("list"))

    return bool(query.get("list")) and not query.get("v")


def platform_from_url(url: str) -> Platform:
    host = _host(url)

    if host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com":
        return Platform.YOUTUBE

    if "tiktok.com" in host:
        return Platform.TIKTOK

    if "instagram.com" in host:
        return Platform.INSTAGRAM

    if "pinterest.com" in host or host == "pin.it":
        return Platform.PINTEREST

    return Platform.UNKNOWN


def choose_platform(original_url: str, resolved_url: str | None = None) -> Platform:
    resolved_url = resolved_url or original_url

    resolved_platform = platform_from_url(resolved_url)
    original_platform = platform_from_url(original_url)

    if resolved_platform != Platform.UNKNOWN:
        return resolved_platform

    return original_platform


def make_url_route_hint(original_url: str, resolved_url: str | None = None) -> UrlRouteHint:
    resolved_url = resolved_url or original_url
    urls = [original_url, resolved_url]

    platform = choose_platform(original_url, resolved_url)
    routing_url = resolved_url or original_url

    if platform == Platform.YOUTUBE:
        if _host_contains_any(urls, "music.youtube.com"):
            if any(_is_youtube_music_playlist_url(url) for url in urls if url):
                return UrlRouteHint(
                    platform=platform,
                    content_type=ContentType.MUSIC_PAGE,
                    action=DownloadAction.DOWNLOAD_ALBUM,
                    routing_url=routing_url,
                    confidence=0.95,
                    reason="youtube_music_playlist",
                )

            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.AUDIO,
                action=DownloadAction.DOWNLOAD_AUDIO,
                routing_url=routing_url,
                confidence=0.95,
                reason="youtube_music_host",
            )

        if _contains_any_path(urls, "/source/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.MUSIC_PAGE,
                action=DownloadAction.DOWNLOAD_AUDIO,
                routing_url=routing_url,
                confidence=0.9,
                reason="youtube_source_audio_page",
            )

        if _contains_any_path(urls, "/shorts/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.SHORTS,
                action=DownloadAction.DOWNLOAD_VIDEO_MAX,
                routing_url=routing_url,
                confidence=0.98,
                reason="youtube_shorts_path",
            )

        return UrlRouteHint(
            platform=platform,
            content_type=ContentType.VIDEO,
            action=DownloadAction.ASK_YOUTUBE_QUALITY,
            routing_url=routing_url,
            confidence=0.9,
            reason="youtube_regular_video",
        )

    if platform == Platform.TIKTOK:
        target_url = resolved_url or original_url
        parsed = urlparse(target_url)
        path = parsed.path.lower()

        if "/photo/" in path or "/share/photo/" in path:
            return UrlRouteHint(
                platform=Platform.TIKTOK,
                content_type=ContentType.POST,
                action=DownloadAction.DOWNLOAD_ALBUM,
                routing_url=target_url,
                confidence=0.95,
                reason="tiktok_photo_path",
            )

        if "/music/" in path:
            return UrlRouteHint(
                platform=Platform.TIKTOK,
                content_type=ContentType.AUDIO,
                action=DownloadAction.DOWNLOAD_AUDIO,
                routing_url=target_url,
                confidence=0.95,
                reason="tiktok_music_path",
            )

        if "/video/" in path:
            return UrlRouteHint(
                platform=Platform.TIKTOK,
                content_type=ContentType.VIDEO,
                action=DownloadAction.DOWNLOAD_VIDEO_MAX,
                routing_url=target_url,
                confidence=0.95,
                reason="tiktok_video_path",
            )

        return UrlRouteHint(
            platform=platform,
            content_type=ContentType.UNKNOWN,
            action=DownloadAction.DOWNLOAD_VIDEO_MAX,
            routing_url=routing_url,
            confidence=0.45,
            reason="tiktok_unknown_short_or_mobile_url",
        )

    if platform == Platform.INSTAGRAM:
        target_url = resolved_url or original_url
        parsed = urlparse(target_url)
        path = parsed.path.lower()

        if "/stories/" in path:
            return UrlRouteHint(
                platform=Platform.INSTAGRAM,
                content_type=ContentType.STORY,
                action=DownloadAction.DOWNLOAD_STORY,
                routing_url=target_url,
                confidence=0.95,
                reason="instagram_story_path",
            )

        if _contains_any_path(urls, "/reels/audio/") or _contains_any_path(urls, "/audio/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.AUDIO,
                action=DownloadAction.DOWNLOAD_AUDIO,
                routing_url=routing_url,
                confidence=0.95,
                reason="instagram_audio_path",
            )

        if _contains_any_path(urls, "/reel/") or _contains_any_path(urls, "/reels/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.REEL,
                action=DownloadAction.DOWNLOAD_VIDEO_MAX,
                routing_url=routing_url,
                confidence=0.95,
                reason="instagram_reel_path",
            )

        if _contains_any_path(urls, "/p/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.POST,
                action=DownloadAction.DOWNLOAD_ALBUM,
                routing_url=routing_url,
                confidence=0.9,
                reason="instagram_post_path",
            )

        return UrlRouteHint(
            platform=platform,
            content_type=ContentType.UNKNOWN,
            action=DownloadAction.DOWNLOAD_ALBUM,
            routing_url=routing_url,
            confidence=0.45,
            reason="instagram_unknown_url",
        )

    if platform == Platform.PINTEREST:
        if _host(original_url) == "pin.it" or _contains_any_path(urls, "/pin/"):
            return UrlRouteHint(
                platform=platform,
                content_type=ContentType.PIN,
                action=DownloadAction.DOWNLOAD_PHOTO,
                routing_url=routing_url,
                confidence=0.9,
                reason="pinterest_pin_url",
            )

        return UrlRouteHint(
            platform=platform,
            content_type=ContentType.PIN,
            action=DownloadAction.DOWNLOAD_PHOTO,
            routing_url=routing_url,
            confidence=0.75,
            reason="pinterest_default_pin",
        )

    return UrlRouteHint(
        platform=Platform.UNKNOWN,
        content_type=ContentType.UNKNOWN,
        action=DownloadAction.UNSUPPORTED,
        routing_url=routing_url,
        confidence=0.0,
        reason="unknown_platform",
    )
