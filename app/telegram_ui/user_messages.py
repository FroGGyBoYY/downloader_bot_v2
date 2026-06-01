from dataclasses import dataclass

from telegram import MessageEntity

from app.services.cookie_auth_service import is_auth_related_error
from app.texts.emojis import CUSTOM_EMOJIS, EMOJI_CHARS
from app.texts.keys import TextKey
from app.texts.renderer import render_text
from app.texts.renderer import utf16_len


@dataclass(frozen=True)
class UserMessage:
    text: str
    entities: list[MessageEntity]


def _message(emoji_key: str, text: str) -> UserMessage:
    emoji = EMOJI_CHARS.get(emoji_key, EMOJI_CHARS["info"])
    full_text = f"{emoji} {text}".strip()
    entities: list[MessageEntity] = []
    custom_emoji_id = CUSTOM_EMOJIS.get(emoji_key)

    if custom_emoji_id:
        entities.append(
            MessageEntity(
                type=MessageEntity.CUSTOM_EMOJI,
                offset=0,
                length=utf16_len(emoji),
                custom_emoji_id=custom_emoji_id,
            )
        )

    return UserMessage(text=full_text, entities=entities)


def localized_message(
    key: str,
    *,
    language_code: str | None = None,
    **variables,
) -> UserMessage:
    text, entities = render_text(
        key,
        language_code=language_code,
        **variables,
    )
    return UserMessage(text=text, entities=entities)


def processing_message(
    platform: str | None = None,
    *,
    content_type: str | None = None,
    url: str | None = None,
    language_code: str | None = None,
) -> UserMessage:
    normalized_url = str(url or "").lower()

    if platform == "youtube" and (
        "music.youtube.com" in normalized_url
        or str(content_type or "").lower() in {"audio", "music", "album", "playlist"}
    ):
        return _message("music", "")

    return _message("hourglass", "")


def platform_limited_message(platform: str | None = None, language_code: str | None = None) -> UserMessage:
    platform_title = {
        "youtube": "YouTube",
        "instagram": "Instagram",
        "tiktok": "TikTok",
        "pinterest": "Pinterest",
    }.get(str(platform or "").lower(), "Платформа")

    return localized_message(
        TextKey.DOWNLOAD_PLATFORM_LIMITED,
        language_code=language_code,
        platform_title=platform_title,
    )


def public_download_error_message(
    error: BaseException | str | None,
    platform: str | None = None,
    language_code: str | None = None,
) -> UserMessage:
    text = str(error or "").lower()

    if is_auth_related_error(error):
        return platform_limited_message(platform, language_code=language_code)

    if any(marker in text for marker in ("timeout", "timed out", "network", "connection", "read operation")):
        return localized_message(TextKey.DOWNLOAD_ERROR_NETWORK, language_code=language_code)

    if any(marker in text for marker in ("private", "unavailable", "deleted", "not found", "404")):
        return localized_message(TextKey.DOWNLOAD_ERROR_UNAVAILABLE, language_code=language_code)

    return localized_message(TextKey.DOWNLOAD_ERROR_GENERIC, language_code=language_code)


def stop_message(text: str) -> UserMessage:
    return _message("stop", text)


def warning_message(text: str) -> UserMessage:
    return _message("warning", text)


def success_message(text: str) -> UserMessage:
    return _message("check", text)
