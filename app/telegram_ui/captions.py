from dataclasses import dataclass
from typing import Optional

from telegram import MessageEntity

from app.texts.emojis import CUSTOM_EMOJIS, EMOJI_CHARS
from app.texts.renderer import utf16_len


@dataclass(frozen=True)
class CaptionPayload:
    text: str
    entities: list[MessageEntity]


PLATFORM_EMOJI_KEYS = {
    "youtube": "youtube",
    "youtube_shorts": "youtube_shorts",
    "tiktok": "tiktok",
    "instagram": "instagram",
    "pinterest": "pinterest",
}


def quality_label_from_int(quality: int | None) -> Optional[str]:
    if quality is None:
        return None

    if quality == 1081:
        return "1080p HQ"

    return f"{quality}p"


def _clean_text(value: str | None, default: str, limit: int) -> str:
    text = str(value or default).replace("\n", " ").strip()
    text = " ".join(text.split())

    if len(text) <= limit:
        return text

    return text[: max(1, limit - 1)].rstrip() + "…"


def _compact_url(url: str | None, limit: int = 260) -> str:
    text = str(url or "").strip()

    if len(text) <= limit:
        return text

    head = max(20, limit // 2)
    tail = max(20, limit - head - 1)
    return text[:head].rstrip() + "…" + text[-tail:].lstrip()


def _bot_url(bot_username: str | None) -> str | None:
    username = str(bot_username or "").strip()

    if not username:
        return None

    if username.startswith("http://") or username.startswith("https://"):
        return username

    if username.startswith("@"):
        username = username[1:]

    if not username:
        return None

    return f"https://t.me/{username}"


def _emoji_key_for_audio_lang(audio_lang: str | None) -> str:
    normalized = str(audio_lang or "auto").lower().strip()

    if normalized in {"ru", "en", "es", "ar", "zh", "th"}:
        return f"lang_{normalized}"

    return "lang_auto"


def _make_entity(
    entity_type: str,
    text: str,
    char_start: int,
    char_length: int,
    *,
    url: str | None = None,
    custom_emoji_id: str | None = None,
) -> MessageEntity:
    kwargs = {
        "type": entity_type,
        "offset": utf16_len(text[:char_start]),
        "length": utf16_len(text[char_start:char_start + char_length]),
    }

    if url:
        kwargs["url"] = url

    if custom_emoji_id:
        kwargs["custom_emoji_id"] = custom_emoji_id

    return MessageEntity(**kwargs)


def _append_line(
    *,
    text_parts: list[str],
    entities: list[MessageEntity],
    emoji_key: str,
    value: str,
    link_url: str | None = None,
) -> None:
    prefix_len = sum(len(part) for part in text_parts)

    if text_parts:
        text_parts.append("\n")
        prefix_len += 1

    emoji_char = EMOJI_CHARS.get(emoji_key, EMOJI_CHARS["info"])
    line = f"{emoji_char} {value}"
    text_parts.append(line)
    current_text = "".join(text_parts)

    custom_emoji_id = CUSTOM_EMOJIS.get(emoji_key)

    if custom_emoji_id:
        entities.append(
            _make_entity(
                MessageEntity.CUSTOM_EMOJI,
                current_text,
                prefix_len,
                len(emoji_char),
                custom_emoji_id=custom_emoji_id,
            )
        )

    if link_url and value:
        entities.append(
            _make_entity(
                MessageEntity.TEXT_LINK,
                current_text,
                prefix_len + len(emoji_char) + 1,
                len(value),
                url=link_url,
            )
        )


def _append_blank(text_parts: list[str]) -> None:
    if text_parts:
        text_parts.append("\n")


def build_content_caption(
    *,
    title: str | None,
    platform: str,
    bot_username: str,
    source_url: str | None = None,
    quality: int | None = None,
    audio_label: str | None = None,
    audio_lang: str | None = None,
    media_type: str | None = None,
    item_index: int = 0,
    item_total: int = 1,
    include_quality: bool = True,
    include_audio: bool = True,
) -> CaptionPayload:
    text_parts: list[str] = []
    entities: list[MessageEntity] = []

    platform_key = PLATFORM_EMOJI_KEYS.get(platform)

    if media_type == "audio":
        title_emoji_key = "music"
    elif platform_key:
        title_emoji_key = platform_key
    elif media_type == "photo":
        title_emoji_key = "photo"
    elif media_type == "video":
        title_emoji_key = "video"
    else:
        title_emoji_key = "download"

    safe_title = _clean_text(title, "Media", 260)
    _append_line(
        text_parts=text_parts,
        entities=entities,
        emoji_key=title_emoji_key,
        value=safe_title,
    )

    if include_audio and audio_label:
        _append_line(
            text_parts=text_parts,
            entities=entities,
            emoji_key=_emoji_key_for_audio_lang(audio_lang),
            value=f"Озвучка: {_clean_text(audio_label, 'Original', 80)}",
        )

    q_label = quality_label_from_int(quality) if include_quality else None

    if q_label:
        _append_line(
            text_parts=text_parts,
            entities=entities,
            emoji_key="quality",
            value=q_label,
        )

    if source_url:
        _append_line(
            text_parts=text_parts,
            entities=entities,
            emoji_key="link",
            value=_compact_url(source_url),
            link_url=source_url,
        )

    bot_link = _bot_url(bot_username)
    bot_label = _clean_text(bot_username, "@Top_Savers_bot", 80)
    _append_blank(text_parts)
    _append_line(
        text_parts=text_parts,
        entities=entities,
        emoji_key="double_heart",
        value=bot_label,
        link_url=bot_link,
    )

    text = "".join(text_parts)

    if len(text) > 1024:
        text = text[:1021].rstrip() + "…"
        entities = [
            entity
            for entity in entities
            if entity.offset + entity.length <= utf16_len(text)
        ]

    return CaptionPayload(text=text, entities=entities)


def build_short_caption(
    *,
    text: str,
    emoji_key: str = "music",
) -> CaptionPayload:
    text_parts: list[str] = []
    entities: list[MessageEntity] = []
    _append_line(
        text_parts=text_parts,
        entities=entities,
        emoji_key=emoji_key,
        value=_clean_text(text, "Media", 500),
    )
    return CaptionPayload(text="".join(text_parts)[:1024], entities=entities)


def build_custom_emoji_lines(lines: list[tuple[str, str]]) -> CaptionPayload:
    text_parts: list[str] = []
    entities: list[MessageEntity] = []

    for emoji_key, value in lines:
        _append_line(
            text_parts=text_parts,
            entities=entities,
            emoji_key=emoji_key,
            value=_clean_text(value, "Media", 500),
        )

    return CaptionPayload(text="".join(text_parts)[:4096], entities=entities)


def build_media_caption(
    *,
    title: Optional[str],
    platform: str,
    bot_username: str,
    quality: int | None = None,
    audio_label: str | None = None,
    item_index: int = 0,
    item_total: int = 1,
) -> str:
    return build_content_caption(
        title=title,
        platform=platform,
        bot_username=bot_username,
        quality=quality,
        audio_label=audio_label,
        item_index=item_index,
        item_total=item_total,
    ).text
