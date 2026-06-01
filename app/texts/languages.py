DEFAULT_LANGUAGE = "ru"


SUPPORTED_LANGUAGES = {
    "ru": {
        "button": "🇷🇺 Русский",
        "title": "Русский",
        "text_language": "ru",
    },
    "en": {
        "button": "🇺🇸 English",
        "title": "English",
        "text_language": "en",
    },
    "es": {
        "button": "🇪🇸 Español",
        "title": "Español",
        "text_language": "es",
    },
    "zh": {
        "button": "🇨🇳 中文",
        "title": "中文",
        "text_language": "zh",
    },
    "ar": {
        "button": "🇦🇪 العربية",
        "title": "العربية",
        "text_language": "ar",
    },
    "th": {
        "button": "🇹🇭 ไทย",
        "title": "ไทย",
        "text_language": "th",
    },
}


def normalize_language_code(language_code: str | None) -> str | None:
    if not language_code:
        return None

    code = str(language_code).lower().strip()

    if code in SUPPORTED_LANGUAGES:
        return code

    base = code.split("-")[0]

    if base in SUPPORTED_LANGUAGES:
        return base

    # Telegram/browser variants
    if base in {"cn", "zh_cn", "zh-hans"}:
        return "zh"

    return None


def get_language_title(language_code: str | None) -> str:
    code = normalize_language_code(language_code)

    if not code:
        return SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]["title"]

    return SUPPORTED_LANGUAGES[code]["title"]


def get_text_language(language_code: str | None) -> str:
    code = normalize_language_code(language_code)

    if not code:
        return DEFAULT_LANGUAGE

    return SUPPORTED_LANGUAGES[code].get("text_language", DEFAULT_LANGUAGE)