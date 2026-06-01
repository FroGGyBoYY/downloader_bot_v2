from dataclasses import dataclass
from typing import Any

from app.downloader.content_types import ContentType, DownloadAction, Platform
from app.downloader.media_inspector import summarize_media
from app.downloader.url_classifier import UrlRouteHint, make_url_route_hint


@dataclass(frozen=True)
class RouteDecision:
    platform: Platform
    content_type: ContentType
    action: DownloadAction

    title: str | None = None
    duration: int | None = None

    entries_count: int = 0
    media_detected_from: str | None = None
    photo_count: int = 0
    video_count: int = 0
    audio_count: int = 0

    routing_url: str | None = None
    url_reason: str | None = None
    url_confidence: float = 0.0
    metadata_status: str = "not_used"
    metadata_error: str | None = None


def _album_content_type(photo_count: int, video_count: int) -> ContentType:
    if photo_count > 0 and video_count > 0:
        return ContentType.MIXED_ALBUM

    if photo_count > 1:
        return ContentType.PHOTO_ALBUM

    if video_count > 1:
        return ContentType.VIDEO

    if photo_count == 1:
        return ContentType.PHOTO

    if video_count == 1:
        return ContentType.VIDEO

    return ContentType.UNKNOWN


def make_fallback_route_decision(
    hint: UrlRouteHint,
    *,
    metadata_error: str | None = None,
) -> RouteDecision:
    photo_count = 0
    video_count = 0
    audio_count = 0

    if hint.platform == Platform.PINTEREST and hint.action == DownloadAction.DOWNLOAD_PHOTO:
        photo_count = 1

    if hint.content_type == ContentType.STORY:
        # Сторис может быть фото или видео, без metadata не знаем.
        pass

    return RouteDecision(
        platform=hint.platform,
        content_type=hint.content_type,
        action=hint.action,
        title=None,
        duration=None,
        entries_count=0,
        media_detected_from="url_fallback",
        photo_count=photo_count,
        video_count=video_count,
        audio_count=audio_count,
        routing_url=hint.routing_url,
        url_reason=hint.reason,
        url_confidence=hint.confidence,
        metadata_status="failed" if metadata_error else "not_used",
        metadata_error=metadata_error,
    )


def make_route_decision(
    original_url: str,
    info: dict[str, Any] | None,
    *,
    resolved_url: str | None = None,
    metadata_error: str | None = None,
) -> RouteDecision:
    hint = make_url_route_hint(original_url, resolved_url)

    if info is None:
        return make_fallback_route_decision(hint, metadata_error=metadata_error)

    summary = summarize_media(info)

    title = info.get("title")
    duration = info.get("duration")

    # ВАЖНО: YouTube Shorts определяем по URL, а не по metadata.
    # yt-dlp иногда возвращает webpage_url как обычный watch?v=...
    if hint.platform == Platform.YOUTUBE:
        if hint.content_type in {ContentType.SHORTS, ContentType.AUDIO, ContentType.MUSIC_PAGE}:
            return RouteDecision(
                platform=hint.platform,
                content_type=hint.content_type,
                action=hint.action,
                title=title,
                duration=duration,
                entries_count=summary.entries_count,
                media_detected_from=summary.detected_from,
                photo_count=summary.photo_count,
                video_count=summary.video_count,
                audio_count=summary.audio_count,
                routing_url=hint.routing_url,
                url_reason=hint.reason,
                url_confidence=hint.confidence,
                metadata_status="ok",
            )

        return RouteDecision(
            platform=hint.platform,
            content_type=ContentType.VIDEO,
            action=DownloadAction.ASK_YOUTUBE_QUALITY,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # Музыка/сторис/пины лучше доверять URL, потому что metadata может быть бедной.
    if hint.content_type in {ContentType.AUDIO, ContentType.MUSIC_PAGE, ContentType.STORY, ContentType.PIN}:
        return RouteDecision(
            platform=hint.platform,
            content_type=hint.content_type,
            action=hint.action,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # Instagram post: если metadata увидела фото/видео - уточняем.
    # Если не увидела - всё равно оставляем post -> download_album.
    if hint.platform == Platform.INSTAGRAM and hint.content_type == ContentType.POST:
        if summary.photo_count + summary.video_count > 1:
            content_type = _album_content_type(summary.photo_count, summary.video_count)
        elif summary.photo_count == 1:
            content_type = ContentType.PHOTO
        elif summary.video_count == 1:
            content_type = ContentType.VIDEO
        else:
            content_type = ContentType.POST

        action = DownloadAction.DOWNLOAD_ALBUM

        if content_type == ContentType.PHOTO:
            action = DownloadAction.DOWNLOAD_PHOTO

        if content_type == ContentType.VIDEO:
            action = DownloadAction.DOWNLOAD_VIDEO_MAX

        return RouteDecision(
            platform=hint.platform,
            content_type=content_type,
            action=action,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # TikTok photo: если URL после редиректа содержит /photo/, не считаем это обычным видео.
    if hint.platform == Platform.TIKTOK and hint.content_type == ContentType.PHOTO_ALBUM:
        content_type = ContentType.PHOTO_ALBUM

        if summary.photo_count == 1:
            content_type = ContentType.PHOTO

        if summary.photo_count > 1:
            content_type = ContentType.PHOTO_ALBUM

        return RouteDecision(
            platform=hint.platform,
            content_type=content_type,
            action=DownloadAction.DOWNLOAD_ALBUM,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # Если metadata явно показала альбом, доверяем metadata.
    if summary.photo_count + summary.video_count > 1:
        return RouteDecision(
            platform=hint.platform,
            content_type=_album_content_type(summary.photo_count, summary.video_count),
            action=DownloadAction.DOWNLOAD_ALBUM,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # Одиночные типы по metadata.
    if summary.photo_count == 1 and summary.video_count == 0:
        return RouteDecision(
            platform=hint.platform,
            content_type=ContentType.PHOTO,
            action=DownloadAction.DOWNLOAD_PHOTO,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    if summary.video_count == 1 or hint.action == DownloadAction.DOWNLOAD_VIDEO_MAX:
        return RouteDecision(
            platform=hint.platform,
            content_type=ContentType.VIDEO if hint.content_type == ContentType.UNKNOWN else hint.content_type,
            action=DownloadAction.DOWNLOAD_VIDEO_MAX,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    if summary.audio_count == 1:
        return RouteDecision(
            platform=hint.platform,
            content_type=ContentType.AUDIO,
            action=DownloadAction.DOWNLOAD_AUDIO,
            title=title,
            duration=duration,
            entries_count=summary.entries_count,
            media_detected_from=summary.detected_from,
            photo_count=summary.photo_count,
            video_count=summary.video_count,
            audio_count=summary.audio_count,
            routing_url=hint.routing_url,
            url_reason=hint.reason,
            url_confidence=hint.confidence,
            metadata_status="ok",
        )

    # Последний fallback: доверяем URL-классификатору.
    return RouteDecision(
        platform=hint.platform,
        content_type=hint.content_type,
        action=hint.action,
        title=title,
        duration=duration,
        entries_count=summary.entries_count,
        media_detected_from=summary.detected_from,
        photo_count=summary.photo_count,
        video_count=summary.video_count,
        audio_count=summary.audio_count,
        routing_url=hint.routing_url,
        url_reason=hint.reason,
        url_confidence=hint.confidence,
        metadata_status="ok",
    )