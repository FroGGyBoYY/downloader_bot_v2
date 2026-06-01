from typing import Any


def normalize_audio_lang(lang: str | None) -> str:
    if not lang:
        return ""

    lang = str(lang).lower().strip()

    if lang.startswith("a."):
        lang = lang[2:]

    return lang.split("-")[0]


def get_audio_label(lang_code: str | None) -> str:
    lang_code = normalize_audio_lang(lang_code)

    if lang_code == "ru":
        return "RU"

    if lang_code == "en":
        return "EN"

    if lang_code == "auto":
        return "Original"

    return "Original"


def get_audio_missing_text(lang_code: str) -> str:
    lang_code = normalize_audio_lang(lang_code)

    if lang_code == "ru":
        return "Русской аудиодорожки нет. Выбери другую."

    if lang_code == "en":
        return "Английской аудиодорожки нет. Выбери другую."

    return "Такой аудиодорожки нет. Выбери другую."


def get_available_audio_languages(info: dict[str, Any]) -> list[str]:
    """
    1 в 1 как в старом боте:
    смотрим ВСЕ formats, где есть acodec,
    не требуем audio-only.
    """
    available: list[str] = []

    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        acodec = fmt.get("acodec")

        if not acodec or acodec == "none":
            continue

        lang = normalize_audio_lang(fmt.get("language"))

        if lang in ("ru", "en") and lang not in available:
            available.append(lang)

    return available


def build_audio_choices(
    available_langs: list[str],
    user_language_code: str | None = None,
    max_choices: int = 3,
) -> list[dict[str, str]]:
    normalized_available = {
        normalize_audio_lang(lang)
        for lang in available_langs
        if normalize_audio_lang(lang)
    }

    choices: list[dict[str, str]] = []

    if "ru" in normalized_available:
        choices.append({"key": "ru", "code": "ru", "title": "RU"})

    if "en" in normalized_available:
        choices.append({"key": "en", "code": "en", "title": "EN"})

    choices.append({"key": "auto", "code": "auto", "title": "Original"})

    return choices


def build_shorts_audio_choices_from_info(
    info: dict[str, Any],
    user_language_code: str | None = None,
    max_extra_choices: int = 3,
) -> list[dict[str, str]]:
    return build_audio_choices(
        available_langs=get_available_audio_languages(info),
        user_language_code=user_language_code,
        max_choices=max_extra_choices,
    )


def should_ask_audio_choice(audio_choices: list[dict[str, str]]) -> bool:
    return len(audio_choices) > 1


def should_ask_shorts_audio_choice(audio_choices: list[dict[str, str]]) -> bool:
    return len(audio_choices) > 1


def get_auto_audio_choice(audio_choices: list[dict[str, str]]) -> dict[str, str]:
    for choice in audio_choices:
        if choice.get("code") == "auto":
            return choice

    return {"key": "auto", "code": "auto", "title": "Original"}


def get_choice_by_key(audio_choices: list[dict[str, str]], key: str) -> dict[str, str] | None:
    for choice in audio_choices:
        if choice.get("key") == key:
            return choice

    return None


def is_audio_lang_available(
    available_langs: list[str] | set[str],
    lang_code: str | None,
) -> bool:
    lang = normalize_audio_lang(lang_code)

    if not lang or lang == "auto":
        return True

    normalized_available = {
        normalize_audio_lang(item)
        for item in available_langs
        if normalize_audio_lang(item)
    }

    return lang in normalized_available
