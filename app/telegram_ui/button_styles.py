from telegram import InlineKeyboardButton

from app.texts.emojis import CUSTOM_EMOJIS


STYLE_ALIASES = {
    "green": "success",
    "success": "success",
    "ok": "success",
    "primary": "primary",
    "blue": "primary",
    "default": "primary",
    "red": "danger",
    "danger": "danger",
    "stop": "danger",
    "black": None,
    "dark": None,
    "gray": None,
    "grey": None,
    "secondary": None,
}


def parse_button_style(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None

    style = None
    icon_custom_emoji_id = None
    raw = str(value).replace(",", " ").replace(";", " ").replace("|", " ")

    for part in raw.split():
        item = part.strip()

        if not item:
            continue

        if "=" in item:
            key, raw_value = item.split("=", 1)
            key = key.lower().strip()
            raw_value = raw_value.strip()

            if key in {"style", "color"}:
                style = STYLE_ALIASES.get(raw_value.lower(), raw_value.lower())
                continue

            if key in {"icon", "emoji", "icon_custom_emoji_id"}:
                icon_custom_emoji_id = CUSTOM_EMOJIS.get(raw_value, raw_value) or None
                continue

        normalized = item.lower()

        if normalized in STYLE_ALIASES:
            style = STYLE_ALIASES[normalized]
            continue

        if item in CUSTOM_EMOJIS:
            icon_custom_emoji_id = CUSTOM_EMOJIS[item] or None
            continue

        if item.isdigit() and len(item) >= 10:
            icon_custom_emoji_id = item

    return style, icon_custom_emoji_id


def build_styled_inline_button(
    text: str,
    callback_data: str,
    style_config: str | None = None,
) -> InlineKeyboardButton:
    if not style_config:
        style_config = "success icon=check" if callback_data == "reqcheck" else "primary"

    style, icon_custom_emoji_id = parse_button_style(style_config)

    return InlineKeyboardButton(
        text[:64],
        callback_data=callback_data,
        style=style,
        icon_custom_emoji_id=icon_custom_emoji_id,
    )


def build_styled_url_button(
    text: str,
    url: str,
    style_config: str | None = None,
) -> InlineKeyboardButton:
    style, icon_custom_emoji_id = parse_button_style(style_config or "primary")

    return InlineKeyboardButton(
        text[:64],
        url=url,
        style=style,
        icon_custom_emoji_id=icon_custom_emoji_id,
    )
