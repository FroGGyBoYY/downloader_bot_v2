import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError, TimedOut
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.settings_repo import get_setting, set_setting
from app.db.users_repo import get_user_language, upsert_user
from app.telegram_ui.button_styles import build_styled_url_button
from app.telegram_ui.keyboards import build_language_keyboard
from app.telegram_ui.messages import reply_text
from app.texts.keys import TextKey
from app.texts.renderer import render_text


logger = logging.getLogger(__name__)


WELCOME_PHOTO_FILE_ID_KEY = "welcome_photo_file_id"
WELCOME_PHOTO_UNIQUE_ID_KEY = "welcome_photo_unique_id"


def _bot_username(settings: Settings, context: ContextTypes.DEFAULT_TYPE) -> str:
    username = str(context.application.bot_data.get("bot_username") or "").strip()

    if not username:
        username = settings.bot_username_text.strip()

    return username.lstrip("@")


def _add_to_group_url(settings: Settings, context: ContextTypes.DEFAULT_TYPE) -> str:
    username = _bot_username(settings, context)
    return f"https://t.me/{username}?startgroup=true"


def _language_for_start(settings: Settings, user) -> str | None:
    if not user:
        return None

    return get_user_language(settings, user.id) or getattr(user, "language_code", None)


def _plain_text(key: str, language_code: str | None = None, **variables) -> str:
    text, _ = render_text(key, language_code=language_code, **variables)
    return text


def _add_to_group_button_text(language_code: str | None = None) -> str:
    return _plain_text(TextKey.ADD_TO_GROUP_BUTTON, language_code=language_code)


def _add_to_group_keyboard(
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    language_code: str | None = None,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        build_styled_url_button(
            text=_add_to_group_button_text(language_code),
            url=_add_to_group_url(settings, context),
            style_config="green icon=telegram",
        )
    ]])


def _start_keyboard(
    settings: Settings,
    context: ContextTypes.DEFAULT_TYPE,
    language_code: str | None = None,
) -> InlineKeyboardMarkup:
    language_keyboard = build_language_keyboard().inline_keyboard
    keyboard = [list(row) for row in language_keyboard]
    keyboard.append([
        build_styled_url_button(
            text=_add_to_group_button_text(language_code),
            url=_add_to_group_url(settings, context),
            style_config="green icon=telegram",
        )
    ])
    return InlineKeyboardMarkup(keyboard)


def _save_welcome_photo_from_message(settings: Settings, message) -> None:
    if not message or not message.photo:
        return

    largest = message.photo[-1]
    set_setting(settings, WELCOME_PHOTO_FILE_ID_KEY, largest.file_id)
    set_setting(settings, WELCOME_PHOTO_UNIQUE_ID_KEY, largest.file_unique_id)


async def _send_start_photo(
    *,
    update: Update,
    settings: Settings,
    text: str,
    entities: list,
    reply_markup: InlineKeyboardMarkup,
) -> bool:
    if not update.message:
        return False

    cached_file_id = get_setting(settings, WELCOME_PHOTO_FILE_ID_KEY)

    if cached_file_id:
        try:
            sent = await update.message.reply_photo(
                photo=cached_file_id,
                caption=text,
                caption_entities=entities,
                reply_markup=reply_markup,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )
            _save_welcome_photo_from_message(settings, sent)
            return True
        except TelegramError as e:
            logger.warning("Cached welcome photo failed, fallback to local/text | error=%s", str(e)[:300])
            set_setting(settings, WELCOME_PHOTO_FILE_ID_KEY, None)
            set_setting(settings, WELCOME_PHOTO_UNIQUE_ID_KEY, None)

    if settings.welcome_photo_path and settings.welcome_photo_path.exists():
        try:
            with settings.welcome_photo_path.open("rb") as photo:
                sent = await update.message.reply_photo(
                    photo=photo,
                    caption=text,
                    caption_entities=entities,
                    reply_markup=reply_markup,
                    read_timeout=settings.send_read_timeout,
                    write_timeout=settings.send_write_timeout,
                    connect_timeout=settings.send_connect_timeout,
                    pool_timeout=settings.send_pool_timeout,
                )
            _save_welcome_photo_from_message(settings, sent)
            return True
        except TimedOut:
            logger.warning(
                "Start welcome photo send timed out | user_id=%s path=%s",
                update.effective_user.id if update.effective_user else None,
                settings.welcome_photo_path,
            )
        except TelegramError as e:
            logger.warning("Local welcome photo failed, fallback to text | error=%s", str(e)[:300])

    return False


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    upsert_user(settings, user)

    language_code = _language_for_start(settings, user)
    reply_markup = _start_keyboard(settings, context, language_code)
    text, entities = render_text(
        TextKey.START,
        language_code=language_code,
    )

    if await _send_start_photo(
        update=update,
        settings=settings,
        text=text,
        entities=entities,
        reply_markup=reply_markup,
    ):
        return

    await reply_text(
        update,
        TextKey.START,
        language_code=language_code,
        reply_markup=reply_markup,
    )


async def add_to_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    upsert_user(settings, user)

    if not update.message:
        return

    language_code = _language_for_start(settings, user)
    text, entities = render_text(
        TextKey.ADD_TO_GROUP,
        language_code=language_code,
    )

    await update.message.reply_text(
        text,
        entities=entities,
        reply_markup=_add_to_group_keyboard(settings, context, language_code),
        disable_web_page_preview=True,
    )


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    upsert_user(settings, user)

    language_code = _language_for_start(settings, user)

    await reply_text(
        update,
        TextKey.MY_ID,
        language_code=language_code,
        user_id=user.id if user else "unknown",
    )


async def welcome_set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    source = message.reply_to_message

    if not source or not source.photo:
        await message.reply_text(
            "Ответь командой /welcome_set на сообщение с фото для приветствия.\n"
            "Кнопки языков и кнопка добавления в группу будут генерироваться ботом автоматически."
        )
        return

    _save_welcome_photo_from_message(settings, source)

    await message.reply_text(
        "Приветственное фото сохранено в кеш Telegram file_id.\n"
        "Текст /start берётся из языковых файлов для ru/en/es/zh/ar/th, кнопки генерируются автоматически."
    )


async def welcome_clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    set_setting(settings, WELCOME_PHOTO_FILE_ID_KEY, None)
    set_setting(settings, WELCOME_PHOTO_UNIQUE_ID_KEY, None)
    await message.reply_text("Кеш приветственного фото очищен. Бот снова будет использовать WELCOME_PHOTO_PATH или текст.")


async def welcome_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    cached_file_id = get_setting(settings, WELCOME_PHOTO_FILE_ID_KEY)
    unique_id = get_setting(settings, WELCOME_PHOTO_UNIQUE_ID_KEY)
    local_photo = settings.welcome_photo_path if settings.welcome_photo_path else None
    local_exists = bool(local_photo and local_photo.exists())

    await message.reply_text(
        "Welcome status\n"
        f"Cached Telegram file_id: {'yes' if cached_file_id else 'no'}\n"
        f"file_unique_id: {unique_id or '-'}\n"
        f"WELCOME_PHOTO_PATH: {local_photo or '-'}\n"
        f"Local file exists: {'yes' if local_exists else 'no'}\n"
        "Text source: TextKey.START in ru/en/es/zh/ar/th"
    )
