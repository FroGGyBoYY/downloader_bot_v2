import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.users_repo import get_user_language, set_user_language
from app.downloader.youtube_audio import (
    get_audio_label,
    get_auto_audio_choice,
    is_audio_lang_available,
    should_ask_audio_choice,
)
from app.telegram_ui.keyboards import (
    LANGUAGE_CALLBACK_PREFIX,
    YOUTUBE_AUDIO_CALLBACK_PREFIX,
    YOUTUBE_QUALITY_CALLBACK_PREFIX,
    YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX,
    build_youtube_shorts_audio_keyboard,
    build_youtube_audio_keyboard,
)
from app.texts.keys import TextKey
from app.texts.languages import get_language_title, normalize_language_code
from app.texts.renderer import render_text

from app.downloader.content_types import ContentType, DownloadAction, Platform
from app.downloader.routing import RouteDecision
from app.services.download_service import process_download_request
from app.services.required_subscriptions_service import send_required_subscriptions_if_needed



logger = logging.getLogger(__name__)


def quality_label_from_int(quality: int) -> str:
    if quality == 1081:
        return "1080p HQ"

    return f"{quality}p"


def _plain_text(key: str, language_code: str | None = None, **variables) -> str:
    text, _ = render_text(key, language_code=language_code, **variables)
    return text


def _language_for_user(settings: Settings, user_id: int | None) -> str | None:
    if not user_id:
        return None

    try:
        return get_user_language(settings, user_id)
    except Exception:
        return None


async def _edit_text_or_caption(message, *, text: str, entities=None, reply_markup=None) -> None:
    if message.caption is not None:
        try:
            await message.edit_caption(
                caption=text,
                caption_entities=entities,
                reply_markup=reply_markup,
            )
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return

            raise

    try:
        await message.edit_text(
            text=text,
            entities=entities,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return

        raise


async def language_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    await query.answer()

    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    data = query.data or ""

    if not data.startswith(LANGUAGE_CALLBACK_PREFIX):
        return

    language_code = data.replace(LANGUAGE_CALLBACK_PREFIX, "", 1)
    language_code = normalize_language_code(language_code)

    if not language_code:
        current_lang = _language_for_user(settings, user.id if user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_INVALID_CHOICE, current_lang), show_alert=True)
        return

    saved = set_user_language(settings, user, language_code)

    if not saved:
        current_lang = _language_for_user(settings, user.id if user else None)
        await query.answer(_plain_text(TextKey.ERROR_INTERNAL, current_lang), show_alert=True)
        return

    text, entities = render_text(
        TextKey.LANGUAGE_SAVED,
        language_code=language_code,
        language_title=get_language_title(language_code),
    )

    if query.message:
        await _edit_text_or_caption(
            query.message,
            text=text,
            entities=entities,
        )

        await send_required_subscriptions_if_needed(
            context=context,
            chat_id=query.message.chat_id,
            user_id=user.id if user else None,
            reply_to_message_id=query.message.message_id,
        )


async def youtube_quality_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data or ""

    if not data.startswith(YOUTUBE_QUALITY_CALLBACK_PREFIX):
        return

    payload = data.replace(YOUTUBE_QUALITY_CALLBACK_PREFIX, "", 1)

    try:
        token, quality_raw = payload.split(":", 1)
        quality = int(quality_raw)
    except Exception:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_INVALID_CHOICE, lang), show_alert=True)
        return

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_CHOICE_EXPIRED, lang), show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        await query.answer(_plain_text(TextKey.CALLBACK_NOT_FOR_YOU, choice.get("language_code")), show_alert=True)
        return

    language_code = choice.get("language_code")
    title = choice.get("title") or "YouTube video"
    audio_choices = choice.get("audio_choices") or []
    quality_label = quality_label_from_int(quality)

    choice["selected_quality"] = quality
    choice["selected_quality_label"] = quality_label

    logger.info(
        "YouTube quality selected | user_id=%s token=%s quality=%s url=%s audio_choices=%s",
        user.id if user else None,
        token,
        quality,
        choice.get("url"),
        audio_choices,
    )

    if not should_ask_audio_choice(audio_choices):
        auto_choice = get_auto_audio_choice(audio_choices)
        choice["selected_audio_lang"] = auto_choice["code"]
        choice["selected_audio_label"] = auto_choice["title"]

        text, entities = render_text(
            TextKey.YOUTUBE_AUDIO_AUTO_SELECTED,
            language_code=language_code,
            quality_label=quality_label,
            audio_label=auto_choice["title"],
        )

        if query.message:
            await query.message.edit_text(
                text=text,
                entities=entities,
                disable_web_page_preview=True,
            )

        logger.info(
            "YouTube audio auto selected | user_id=%s token=%s audio=%s",
            user.id if user else None,
            token,
            auto_choice,
        )
        
        if user and query.message:
            route = RouteDecision(
                platform=Platform.YOUTUBE,
                content_type=ContentType.VIDEO,
                action=DownloadAction.ASK_YOUTUBE_QUALITY,
                title=choice.get("title"),
                routing_url=choice.get("resolved_url") or choice.get("url"),
                metadata_status="ok",
            )

            await process_download_request(
                context=context,
                chat_id=query.message.chat_id,
                user=user,
                language_code=language_code,
                original_url=choice.get("url"),
                resolved_url=choice.get("resolved_url"),
                route=route,
                reply_to_message_id=None,
                quality=quality,
                audio_lang=auto_choice["code"],
                audio_label=auto_choice["title"],
            )       
        return

    text, entities = render_text(
        TextKey.YOUTUBE_CHOOSE_AUDIO,
        language_code=language_code,
        quality_label=quality_label,
        title=title,
    )

    if query.message:
        await query.message.edit_text(
            text=text,
            entities=entities,
            reply_markup=build_youtube_audio_keyboard(token, quality, audio_choices),
            disable_web_page_preview=True,
        )


async def youtube_audio_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = query.data or ""

    if not data.startswith(YOUTUBE_AUDIO_CALLBACK_PREFIX):
        return

    payload = data.replace(YOUTUBE_AUDIO_CALLBACK_PREFIX, "", 1)

    try:
        token, quality_raw, audio_lang = payload.split(":", 2)
        quality = int(quality_raw)
    except Exception:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_INVALID_CHOICE, lang), show_alert=True)
        return

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_CHOICE_EXPIRED, lang), show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        await query.answer(_plain_text(TextKey.CALLBACK_NOT_FOR_YOU, choice.get("language_code")), show_alert=True)
        return

    language_code = choice.get("language_code")
    quality_label = quality_label_from_int(quality)

    available_audio_langs = choice.get("available_audio_langs") or []

    if audio_lang != "auto" and not is_audio_lang_available(available_audio_langs, audio_lang):
        await query.answer(_plain_text(TextKey.YOUTUBE_AUDIO_MISSING, choice.get("language_code")), show_alert=True)
        return

    audio_label = get_audio_label(audio_lang)

    choice["selected_quality"] = quality
    choice["selected_quality_label"] = quality_label
    choice["selected_audio_lang"] = audio_lang
    choice["selected_audio_label"] = audio_label

    logger.info(
        "YouTube audio selected | user_id=%s token=%s quality=%s audio=%s url=%s",
        user.id if user else None,
        token,
        quality,
        audio_lang,
        choice.get("url"),
    )
    if user and query.message:
        route = RouteDecision(
            platform=Platform.YOUTUBE,
            content_type=ContentType.VIDEO,
            action=DownloadAction.ASK_YOUTUBE_QUALITY,
            title=choice.get("title"),
            routing_url=choice.get("resolved_url") or choice.get("url"),
            metadata_status="ok",
        )

        await process_download_request(
            context=context,
            chat_id=query.message.chat_id,
            user=user,
            language_code=language_code,
            original_url=choice.get("url"),
            resolved_url=choice.get("resolved_url"),
            route=route,
            reply_to_message_id=None,
            quality=quality,
            audio_lang=audio_lang,
            audio_label=audio_label,
        )


    text, entities = render_text(
        TextKey.YOUTUBE_AUDIO_SELECTED,
        language_code=language_code,
        quality_label=quality_label,
        audio_label=audio_label,
    )

    if query.message:
        await query.message.edit_text(
            text=text,
            entities=entities,
            disable_web_page_preview=True,
        )

async def youtube_shorts_audio_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX):
        return

    payload = data.replace(YOUTUBE_SHORTS_AUDIO_CALLBACK_PREFIX, "", 1)

    try:
        token, choice_key = payload.split(":", 1)
    except Exception:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_INVALID_CHOICE, lang), show_alert=True)
        return

    pending_choices: dict = context.application.bot_data.setdefault("pending_choices", {})
    choice = pending_choices.get(token)

    if not choice:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.CALLBACK_CHOICE_EXPIRED, lang), show_alert=True)
        return

    user = update.effective_user

    if user and choice.get("user_id") != user.id:
        await query.answer(_plain_text(TextKey.CALLBACK_NOT_FOR_YOU, choice.get("language_code")), show_alert=True)
        return

    audio_choices_by_key = choice.get("audio_choices_by_key") or {}
    selected_choice = audio_choices_by_key.get(choice_key)

    if not selected_choice:
        for item in choice.get("audio_choices") or []:
            if item.get("key") == choice_key or item.get("code") == choice_key:
                selected_choice = item
                break

    if not selected_choice:
        await query.answer(_plain_text(TextKey.CALLBACK_CHOICE_EXPIRED, choice.get("language_code")), show_alert=True)
        return

    audio_lang = selected_choice.get("code", "auto")
    audio_label = selected_choice.get("title", get_audio_label(audio_lang))
    audio_format_id = selected_choice.get("format_id")

    await query.answer()

    language_code = choice.get("language_code")
    title = choice.get("title") or "YouTube Shorts"
    available_audio_langs = choice.get("available_audio_langs") or []

    logger.info(
        "YouTube Shorts audio selected | user_id=%s token=%s choice_key=%s audio=%s audio_format_id=%s url=%s available=%s selected_choice=%s",
        user.id if user else None,
        token,
        choice_key,
        audio_lang,
        audio_format_id,
        choice.get("url"),
        available_audio_langs,
        selected_choice,
    )

    text, entities = render_text(
        TextKey.YOUTUBE_SHORTS_AUDIO_SELECTED,
        language_code=language_code,
        audio_label=audio_label,
    )

    if query.message:
        await query.message.edit_text(
            text=text,
            entities=entities,
            disable_web_page_preview=True,
        )

    if user and query.message:
        route = RouteDecision(
            platform=Platform.YOUTUBE,
            content_type=ContentType.SHORTS,
            action=DownloadAction.DOWNLOAD_VIDEO_MAX,
            title=title,
            routing_url=choice.get("resolved_url") or choice.get("url"),
            metadata_status="ok",
        )

        await process_download_request(
            context=context,
            chat_id=query.message.chat_id,
            user=user,
            language_code=language_code,
            original_url=choice.get("url"),
            resolved_url=choice.get("resolved_url"),
            route=route,
            reply_to_message_id=None,
            audio_lang=audio_lang,
            audio_label=audio_label,
        )
