from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.texts.emojis import CUSTOM_EMOJIS
from app.texts.languages import SUPPORTED_LANGUAGES


LANGUAGE_CALLBACK_PREFIX = "lang:"
YOUTUBE_QUALITY_CALLBACK_PREFIX = "ytq:"
YOUTUBE_AUDIO_CALLBACK_PREFIX = "yta:"
YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX = "yt:"
YOUTUBE_BACK_CALLBACK_PREFIX = "ytback:"


def build_language_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []

    for code, data in SUPPORTED_LANGUAGES.items():
        row.append(
            InlineKeyboardButton(
                data.get("title") or data["button"],
                callback_data=f"{LANGUAGE_CALLBACK_PREFIX}{code}",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get(f"lang_{code}") or None,
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


def build_youtube_quality_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "720p",
                callback_data=f"{YOUTUBE_QUALITY_CALLBACK_PREFIX}{token}:720",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
            InlineKeyboardButton(
                "1080p",
                callback_data=f"{YOUTUBE_QUALITY_CALLBACK_PREFIX}{token}:1080",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
        ],
        [
            InlineKeyboardButton(
                "1080p HQ",
                callback_data=f"{YOUTUBE_QUALITY_CALLBACK_PREFIX}{token}:1081",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get("quality") or None,
            ),
        ],
    ])


def build_youtube_audio_keyboard(
    token: str,
    quality: int,
    audio_choices: list[dict[str, str]],
) -> InlineKeyboardMarkup:
    lang_choices = [
        choice for choice in audio_choices
        if choice.get("code") != "auto"
    ]

    keyboard = []

    if lang_choices:
        keyboard.append([
            InlineKeyboardButton(
                choice["title"],
                callback_data=f"{YOUTUBE_AUDIO_CALLBACK_PREFIX}{token}:{quality}:{choice['code']}",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get(f"lang_{choice['code']}") or None,
            )
            for choice in lang_choices[:3]
        ])

    keyboard.append([
        InlineKeyboardButton(
            "Original",
            callback_data=f"{YOUTUBE_AUDIO_CALLBACK_PREFIX}{token}:{quality}:auto",
            icon_custom_emoji_id=CUSTOM_EMOJIS.get("music") or None,
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Назад к качеству",
            callback_data=f"{YOUTUBE_BACK_CALLBACK_PREFIX}{token}",
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def build_youtube_shorts_audio_keyboard(
    token: str,
    audio_choices: list[dict[str, str]],
) -> InlineKeyboardMarkup:
    lang_choices = [
        choice for choice in audio_choices
        if choice.get("code") != "auto"
    ]

    keyboard = []

    if lang_choices:
        keyboard.append([
            InlineKeyboardButton(
                choice["title"],
                callback_data=f"{YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX}{token}:{choice['code']}",
                icon_custom_emoji_id=CUSTOM_EMOJIS.get(f"lang_{choice['code']}") or None,
            )
            for choice in lang_choices[:3]
        ])

    keyboard.append([
        InlineKeyboardButton(
            "Original",
            callback_data=f"{YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX}{token}:auto",
            icon_custom_emoji_id=CUSTOM_EMOJIS.get("music") or None,
        )
    ])

    return InlineKeyboardMarkup(keyboard)
