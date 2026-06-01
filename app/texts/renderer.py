from collections import UserDict
from typing import Any, Optional

from telegram import MessageEntity

from app.texts.ar import TEXTS_AR
from app.texts.emojis import CUSTOM_EMOJIS, EMOJI_CHARS
from app.texts.en import TEXTS_EN
from app.texts.es import TEXTS_ES
from app.texts.languages import DEFAULT_LANGUAGE, get_text_language
from app.texts.ru import TEXTS_RU
from app.texts.th import TEXTS_TH
from app.texts.zh import TEXTS_ZH


TEXT_CATALOGS = {
    "ru": TEXTS_RU,
    "en": TEXTS_EN,
    "es": TEXTS_ES,
    "zh": TEXTS_ZH,
    "ar": TEXTS_AR,
    "th": TEXTS_TH,
}


class SafeFormatDict(UserDict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _find_all(text: str, target: str) -> list[int]:
    if not target:
        return []

    positions: list[int] = []
    start = 0

    while True:
        index = text.find(target, start)

        if index == -1:
            break

        positions.append(index)
        start = index + len(target)

    return positions


def _make_entity(
    entity_type: str,
    text: str,
    target: str,
    *,
    custom_emoji_id: Optional[str] = None,
    first_only: bool = False,
) -> list[MessageEntity]:
    entities: list[MessageEntity] = []
    positions = _find_all(text, target)

    if first_only:
        positions = positions[:1]

    for pos in positions:
        kwargs: dict[str, Any] = {
            "type": entity_type,
            "offset": utf16_len(text[:pos]),
            "length": utf16_len(target),
        }

        if custom_emoji_id:
            kwargs["custom_emoji_id"] = custom_emoji_id

        entities.append(MessageEntity(**kwargs))

    return entities


def _get_template(key: str, language_code: str | None) -> dict[str, Any] | None:
    text_language = get_text_language(language_code)
    catalog = TEXT_CATALOGS.get(text_language) or TEXT_CATALOGS[DEFAULT_LANGUAGE]

    template = catalog.get(key)

    if template:
        return template

    return TEXT_CATALOGS[DEFAULT_LANGUAGE].get(key)


def render_text(
    key: str,
    *,
    language_code: str | None = None,
    **variables: Any,
) -> tuple[str, list[MessageEntity]]:
    template = _get_template(key, language_code)

    if not template:
        return key, []

    format_values = SafeFormatDict()

    for emoji_name, emoji_char in EMOJI_CHARS.items():
        format_values[emoji_name] = emoji_char

    for var_key, var_value in variables.items():
        format_values[var_key] = "" if var_value is None else str(var_value)

    text = template["text"].format_map(format_values)

    entities: list[MessageEntity] = []

    for placeholder_name, custom_emoji_key in template.get("emoji", {}).items():
        emoji_char = EMOJI_CHARS.get(placeholder_name)
        custom_emoji_id = CUSTOM_EMOJIS.get(custom_emoji_key)

        if emoji_char and custom_emoji_id:
            entities.extend(
                _make_entity(
                    MessageEntity.CUSTOM_EMOJI,
                    text,
                    emoji_char,
                    custom_emoji_id=custom_emoji_id,
                )
            )

    for code_var in template.get("code", []):
        value = str(variables.get(code_var, "")).strip()

        if value:
            entities.extend(
                _make_entity(
                    MessageEntity.CODE,
                    text,
                    value,
                    first_only=True,
                )
            )

    return text, entities