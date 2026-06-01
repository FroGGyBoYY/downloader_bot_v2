import csv
import asyncio
import re
import tempfile
from urllib.parse import urlparse

from telegram import InlineKeyboardMarkup, Message, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.ads_repo import (
    AFTER_DOWNLOAD_AD,
    ACTIVE,
    DELETED,
    PAUSED,
    SCHEDULED_AD,
    create_ad_campaign,
    get_ad_campaign,
    get_ad_unique_event_counts,
    list_ad_buttons,
    list_ad_campaigns,
    list_current_ad_campaigns,
    set_ad_status,
)
from app.db.cookie_auth_repo import log_admin_action, to_local_display
from app.db.database import db_connect
from app.db.users_repo import get_full_name, list_friend_users, list_message_target_users, set_user_friend
from app.services.ads_service import AD_CLICK_PREFIX, handle_ad_click
from app.telegram_ui.button_styles import build_styled_url_button


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return is_admin(settings, user_id)


def _command_tail(message: Message) -> str:
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _legacy_add_tail(message: Message) -> str:
    text = (message.text or "").strip()

    if not text.lower().startswith("add"):
        return ""

    return text[3:].strip()


def _validate_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_button_config(raw: str) -> tuple[str | None, str | None, str | None, str | None]:
    raw = raw.strip()

    if not raw:
        return None, None, None, None

    parts = [part.strip() for part in raw.split("|")]

    if len(parts) >= 2:
        button_text = parts[0]
        button_url = parts[1]
        button_style = parts[2] if len(parts) >= 3 and parts[2] else None

        if not button_text:
            return None, None, None, "Название кнопки пустое."

        if not _validate_url(button_url):
            return None, None, None, "Ссылка кнопки должна начинаться с http:// или https://."

        return button_text[:64], button_url, button_style, None

    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    if len(lines) >= 2:
        button_text = lines[0]
        button_url = lines[1]
        button_style = lines[2] if len(lines) >= 3 else None

        if not _validate_url(button_url):
            return None, None, None, "Ссылка кнопки должна начинаться с http:// или https://."

        return button_text[:64], button_url, button_style, None

    match = re.search(r"https?://\S+", raw)

    if match:
        button_url = match.group(0).strip()
        button_text = raw[:match.start()].strip() or "Открыть"

        return button_text[:64], button_url, None, None

    return None, None, None, "Для кнопки укажи: название | https://ссылка"


def _parse_button_configs(raw: str) -> tuple[list[dict], str | None]:
    raw = raw.strip()

    if not raw:
        return [], None

    chunks: list[str] = []

    for line in raw.splitlines():
        for chunk in re.split(r"\s*\|\|\s*", line):
            chunk = chunk.strip()

            if chunk:
                chunks.append(chunk)

    if len(chunks) > 1:
        buttons = []

        for chunk in chunks:
            button_text, button_url, button_style, error = _parse_button_config(chunk)

            if error:
                return [], error

            if button_text and button_url:
                buttons.append({
                    "button_text": button_text,
                    "button_url": button_url,
                    "button_style": button_style,
                })

        return buttons, None

    button_text, button_url, button_style, error = _parse_button_config(chunks[0] if chunks else raw)

    if error:
        return [], error

    if not button_text or not button_url:
        return [], None

    return [{
        "button_text": button_text,
        "button_url": button_url,
        "button_style": button_style,
    }], None


def _source_type(message: Message) -> str:
    if message.video:
        return "video"
    if message.photo:
        return "photo"
    if message.animation:
        return "animation"
    if message.document:
        return "document"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.text:
        return "text"
    return "message"


def _format_ad_brief(row) -> str:
    return (
        f"#{row['id']} | {row['status']} | {row['source_type'] or '-'} | "
        f"показы {row['impressions_count']} | клики {row['clicks_count']} | "
        f"блок {row['blocked_count']} | ошибки {row['failed_count']}"
    )


async def _send_ad_campaigns_txt(
    message: Message,
    settings: Settings,
    *,
    campaign_type: str = AFTER_DOWNLOAD_AD,
    filename: str = "ad_campaigns.txt",
) -> None:
    temp_root = settings.base_dir / "media" / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)

    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            a.*,
            COALESCE(
                (
                    SELECT GROUP_CONCAT(
                        b.button_text || ' -> ' || b.button_url ||
                        CASE
                            WHEN b.button_style IS NULL OR b.button_style = '' THEN ''
                            ELSE ' [' || b.button_style || ']'
                        END,
                        ' || '
                    )
                    FROM ad_buttons b
                    WHERE b.ad_id = a.id
                ),
                CASE
                    WHEN a.button_text IS NULL OR a.button_url IS NULL THEN ''
                    ELSE a.button_text || ' -> ' || a.button_url ||
                        CASE
                            WHEN a.button_style IS NULL OR a.button_style = '' THEN ''
                            ELSE ' [' || a.button_style || ']'
                        END
                END
            ) AS buttons
        FROM ad_campaigns a
        WHERE a.campaign_type = ?
        ORDER BY a.id DESC
    """, (campaign_type,)).fetchall()
    conn.close()

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        suffix="_ad_campaigns.txt",
        dir=temp_root,
        delete=False,
    ) as fp:
        path = fp.name
        writer = csv.writer(fp, delimiter="\t")
        columns = [
            "id",
            "status",
            "campaign_type",
            "source_type",
            "buttons",
            "impressions_count",
            "clicks_count",
            "blocked_count",
            "failed_count",
            "created_by",
            "created_at",
            "updated_at",
            "last_shown_at",
            "source_chat_id",
            "source_message_id",
        ]
        writer.writerow(columns)

        for row in rows:
            writer.writerow([(row[column] if row[column] is not None else "") for column in columns])

    with open(path, "rb") as document:
        await message.reply_document(
            document=document,
            filename=filename,
            caption=f"Выгрузка рекламных кампаний: {len(rows)} строк.",
        )


async def _create_ad_from_reply(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tail: str,
    silent_for_non_admin: bool = False,
    campaign_type: str = AFTER_DOWNLOAD_AD,
    campaign_title: str = "Реклама",
    admin_action: str = "ad_create",
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        if not silent_for_non_admin:
            await message.reply_text("Эта команда доступна только админу.")
        return

    source = message.reply_to_message

    if not source:
        await message.reply_text("Ответь командой на сообщение, которое нужно показывать как рекламу.")
        return

    buttons, error = _parse_button_configs(tail)

    if error:
        await message.reply_text(error)
        return

    first_button = buttons[0] if buttons else {}

    ad_id = create_ad_campaign(
        settings,
        campaign_type=campaign_type,
        source_chat_id=source.chat_id,
        source_message_id=source.message_id,
        source_type=_source_type(source),
        button_text=first_button.get("button_text"),
        button_url=first_button.get("button_url"),
        button_style=first_button.get("button_style"),
        buttons=buttons,
        created_by=user.id if user else None,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action=admin_action,
        target=str(ad_id),
        details=f"source={source.chat_id}:{source.message_id} buttons={len(buttons)}",
    )

    button_text = first_button.get("button_text")
    button_url = first_button.get("button_url")
    button_style = first_button.get("button_style")

    lines = [
        f"Реклама #{ad_id} добавлена и запущена.",
        f"Тип сообщения: {_source_type(source)}",
    ]

    if button_text and button_url:
        lines.append(f"Кнопка: {button_text}")

    if button_style:
        lines.append("Стиль кнопки будет применен в Telegram-кнопке.")

    if len(buttons) > 1:
        lines.append(f"Кнопок всего: {len(buttons)}")

        for index, button in enumerate(buttons, 1):
            style = button.get("button_style") or ("success" if index == 1 else "primary")
            lines.append(f"{index}. {button['button_text']} | style={style}")

    await message.reply_text("\n".join(lines))


async def ad_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message:
        return

    await _create_ad_from_reply(
        update=update,
        context=context,
        tail=_command_tail(message),
    )


async def ad8_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message:
        return

    await _create_ad_from_reply(
        update=update,
        context=context,
        tail=_command_tail(message),
        campaign_type=SCHEDULED_AD,
        campaign_title="Реклама каждые 8 часов",
        admin_action="ad8_create",
    )


async def ad_add_reply_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    if not message:
        return

    await _create_ad_from_reply(
        update=update,
        context=context,
        tail=_legacy_add_tail(message),
        silent_for_non_admin=True,
    )


async def ad_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    rows = list_current_ad_campaigns(settings)

    if not rows:
        await message.reply_text("Активных или поставленных на паузу рекламных кампаний пока нет.")
        return

    lines = ["Реклама: текущие кампании ACTIVE/PAUSED"]

    for row in rows:
        button = "кнопка" if row["button_text"] and row["button_url"] else "без кнопки"
        lines.append(
            f"#{row['id']} | {row['status']} | {button} | "
            f"показы {row['impressions_count']} | клики {row['clicks_count']} | "
            f"блок {row['blocked_count']} | ошибки {row['failed_count']}"
        )

    await message.reply_text("\n".join(lines)[:3900])


async def ad_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _command_tail(message)

    if not tail.isdigit():
        await message.reply_text("Использование: /ad_del 1")
        return

    ad_id = int(tail)
    row = get_ad_campaign(settings, ad_id)

    if not row or row["campaign_type"] != AFTER_DOWNLOAD_AD:
        await message.reply_text("Такой рекламы после скачивания нет.")
        return

    if not set_ad_status(settings, ad_id, DELETED):
        await message.reply_text("Такой рекламы нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="ad_delete",
        target=str(ad_id),
        details="soft_delete",
    )

    await message.reply_text(f"Реклама #{ad_id} удалена из текущего списка, но сохранена в истории.")


async def ad_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _command_tail(message)

    if not tail:
        rows = list_ad_campaigns(settings, limit=30)

        if not rows:
            await message.reply_text("Истории рекламных кампаний пока нет.")
            return

        lines = ["История рекламы: последние 30 кампаний"]

        for row in rows:
            lines.append(_format_ad_brief(row))

        lines.append("")
        lines.append("Подробно по кампании: /ad_stats 1")
        lines.append("Полная выгрузка: /ad_stats_txt")
        await message.reply_text("\n".join(lines)[:3900])
        return

    if not tail.isdigit():
        await message.reply_text("Использование: /ad_stats или /ad_stats 1")
        return

    row = get_ad_campaign(settings, int(tail))

    if not row or row["campaign_type"] != AFTER_DOWNLOAD_AD:
        await message.reply_text("Такой рекламы после скачивания нет.")
        return

    unique_counts = get_ad_unique_event_counts(settings, int(row["id"]))

    lines = [
        f"Реклама #{row['id']}",
        f"Статус: {row['status']}",
        f"Тип: {row['source_type'] or '-'}",
        f"Показы: {row['impressions_count']}",
        f"Уникальных зрителей: {unique_counts.get('impression', 0)}",
        f"Клики: {row['clicks_count']}",
        f"Уникальных кликов: {unique_counts.get('click', 0)}",
        f"Блокировки/Forbidden: {row['blocked_count']}",
        f"Уникальных блокировок/Forbidden: {unique_counts.get('blocked', 0)}",
        f"Ошибки отправки: {row['failed_count']}",
        f"Кнопка: {row['button_text'] or '-'}",
        f"Ссылка: {row['button_url'] or '-'}",
        f"Создана: {to_local_display(row['created_at'], settings.local_tz_hours)}",
        f"Последний показ: {to_local_display(row['last_shown_at'], settings.local_tz_hours)}",
    ]

    await message.reply_text("\n".join(lines)[:3900])


async def ad_stats_txt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    await _send_ad_campaigns_txt(message, settings)


async def ad_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    command = (message.text or "").split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()
    status = ACTIVE if command == "ad_on" else PAUSED
    tail = _command_tail(message)

    if not tail.isdigit():
        await message.reply_text(f"Использование: /{command} 1")
        return

    ad_id = int(tail)
    row = get_ad_campaign(settings, ad_id)

    if not row or row["campaign_type"] != AFTER_DOWNLOAD_AD:
        await message.reply_text("Такой рекламы после скачивания нет.")
        return

    if not set_ad_status(settings, ad_id, status):
        await message.reply_text("Такой рекламы нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="ad_status",
        target=str(ad_id),
        details=status,
    )

    await message.reply_text(f"Реклама #{ad_id}: {status}.")


async def ad8_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    rows = list_current_ad_campaigns(settings, campaign_type=SCHEDULED_AD)

    if not rows:
        await message.reply_text("Активных или поставленных на паузу реклам каждые 8 часов пока нет.")
        return

    lines = ["Реклама каждые 8 часов: текущие кампании ACTIVE/PAUSED"]

    for row in rows:
        buttons = list_ad_buttons(settings, int(row["id"]))
        button_label = f"кнопок {len(buttons)}" if buttons else "без кнопок"
        lines.append(
            f"#{row['id']} | {row['status']} | {button_label} | "
            f"показы {row['impressions_count']} | клики {row['clicks_count']} | "
            f"блок {row['blocked_count']} | ошибки {row['failed_count']}"
        )

    await message.reply_text("\n".join(lines)[:3900])


async def ad8_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _command_tail(message)

    if not tail.isdigit():
        await message.reply_text("Использование: /ad8_del 1")
        return

    ad_id = int(tail)
    row = get_ad_campaign(settings, ad_id)

    if not row or row["campaign_type"] != SCHEDULED_AD:
        await message.reply_text("Такой рекламы каждые 8 часов нет.")
        return

    if not set_ad_status(settings, ad_id, DELETED):
        await message.reply_text("Такой рекламы каждые 8 часов нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="ad8_delete",
        target=str(ad_id),
        details="soft_delete",
    )

    await message.reply_text(f"Реклама каждые 8 часов #{ad_id} удалена из текущего списка, но сохранена в истории.")


async def ad8_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _command_tail(message)

    if not tail:
        rows = list_ad_campaigns(settings, limit=30, campaign_type=SCHEDULED_AD)

        if not rows:
            await message.reply_text("Истории рекламы каждые 8 часов пока нет.")
            return

        lines = ["История рекламы каждые 8 часов: последние 30 кампаний"]

        for row in rows:
            lines.append(_format_ad_brief(row))

        lines.append("")
        lines.append("Подробно по кампании: /ad8_stats 1")
        lines.append("Полная выгрузка: /ad8_stats_txt")
        await message.reply_text("\n".join(lines)[:3900])
        return

    if not tail.isdigit():
        await message.reply_text("Использование: /ad8_stats или /ad8_stats 1")
        return

    row = get_ad_campaign(settings, int(tail))

    if not row or row["campaign_type"] != SCHEDULED_AD:
        await message.reply_text("Такой рекламы каждые 8 часов нет.")
        return

    unique_counts = get_ad_unique_event_counts(settings, int(row["id"]))
    buttons = list_ad_buttons(settings, int(row["id"]))

    lines = [
        f"Реклама каждые 8 часов #{row['id']}",
        f"Статус: {row['status']}",
        f"Тип сообщения: {row['source_type'] or '-'}",
        f"Показы: {row['impressions_count']}",
        f"Уникальных зрителей: {unique_counts.get('impression', 0)}",
        f"Клики: {row['clicks_count']}",
        f"Уникальных кликов: {unique_counts.get('click', 0)}",
        f"Блокировки/Forbidden: {row['blocked_count']}",
        f"Ошибки отправки: {row['failed_count']}",
        f"Создана: {to_local_display(row['created_at'], settings.local_tz_hours)}",
        f"Последний показ: {to_local_display(row['last_shown_at'], settings.local_tz_hours)}",
        "",
        "Кнопки:",
    ]

    if buttons:
        for index, button in enumerate(buttons, 1):
            lines.append(
                f"{index}. {button['button_text']} | {button['button_url']} | {button['button_style'] or '-'}"
            )
    else:
        lines.append("-")

    await message.reply_text("\n".join(lines)[:3900])


async def ad8_stats_txt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    await _send_ad_campaigns_txt(
        message,
        settings,
        campaign_type=SCHEDULED_AD,
        filename="ad8_campaigns.txt",
    )


async def ad8_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    command = (message.text or "").split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()
    status = ACTIVE if command in {"ad8_on", "scheduled_ad_on"} else PAUSED
    tail = _command_tail(message)

    if not tail.isdigit():
        await message.reply_text(f"Использование: /{command} 1")
        return

    ad_id = int(tail)
    row = get_ad_campaign(settings, ad_id)

    if not row or row["campaign_type"] != SCHEDULED_AD:
        await message.reply_text("Такой рекламы каждые 8 часов нет.")
        return

    if not set_ad_status(settings, ad_id, status):
        await message.reply_text("Такой рекламы каждые 8 часов нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="ad8_status",
        target=str(ad_id),
        details=status,
    )

    await message.reply_text(f"Реклама каждые 8 часов #{ad_id}: {status}.")


def _build_buttons_reply_markup(buttons: list[dict]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None

    keyboard = []

    for index, button in enumerate(buttons):
        button_text = str(button.get("button_text") or "").strip()
        button_url = str(button.get("button_url") or "").strip()

        if not button_text or not button_url:
            continue

        style = str(button.get("button_style") or "").strip() or ("success" if index == 0 else "primary")

        keyboard.append([
            build_styled_url_button(
                text=button_text,
                url=button_url,
                style_config=style,
            )
        ])

    if not keyboard:
        return None

    return InlineKeyboardMarkup(keyboard)


def _broadcast_blocked(error: Exception) -> bool:
    if isinstance(error, Forbidden):
        return True

    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "bot was blocked",
            "user is deactivated",
            "forbidden",
            "chat not found",
            "bot can't initiate conversation",
        )
    )


async def _run_broadcast(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    admin_chat_id: int,
    admin_id: int | None,
    source_chat_id: int,
    source_message_id: int,
    buttons: list[dict],
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    rows = list_message_target_users(settings, include_friends=True)
    reply_markup = _build_buttons_reply_markup(buttons)
    sent_count = 0
    failed_count = 0
    blocked_count = 0

    for row in rows:
        user_id = int(row["user_id"])

        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=reply_markup,
                read_timeout=settings.send_read_timeout,
                write_timeout=settings.send_write_timeout,
                connect_timeout=settings.send_connect_timeout,
                pool_timeout=settings.send_pool_timeout,
            )
            sent_count += 1

        except TelegramError as e:
            failed_count += 1

            if _broadcast_blocked(e):
                blocked_count += 1

        await asyncio.sleep(0.05)

    log_admin_action(
        settings,
        admin_id=admin_id,
        action="broadcast",
        details=f"users={len(rows)} sent={sent_count} failed={failed_count} blocked={blocked_count} buttons={len(buttons)}",
    )

    await context.bot.send_message(
        chat_id=admin_chat_id,
        text=(
            "Broadcast finished\n"
            f"Users: {len(rows)}\n"
            f"Sent: {sent_count}\n"
            f"Failed: {failed_count}\n"
            f"Blocked: {blocked_count}"
        ),
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    source = message.reply_to_message

    if not source:
        await message.reply_text(
            "Ответь командой /broadcast на сообщение, которое нужно разослать всем пользователям.\n"
            "Кнопки: /broadcast Текст | https://url | green || Второй текст | https://url | red"
        )
        return

    buttons, error = _parse_button_configs(_command_tail(message))

    if error:
        await message.reply_text(error)
        return

    rows = list_message_target_users(settings, include_friends=True)

    if not rows:
        await message.reply_text("Нет пользователей для рассылки.")
        return

    await message.reply_text(
        f"Broadcast started: пользователей {len(rows)}, кнопок {len(buttons)}. "
        "Когда закончу, пришлю итог."
    )

    context.application.create_task(
        _run_broadcast(
            context=context,
            admin_chat_id=message.chat_id,
            admin_id=user.id if user else None,
            source_chat_id=source.chat_id,
            source_message_id=source.message_id,
            buttons=buttons,
        ),
        update=update,
    )


def _friend_target_from_message(message: Message) -> tuple[int | None, str | None, str | None]:
    tail = _command_tail(message)

    if tail:
        match = re.search(r"\d{5,}", tail)

        if match:
            return int(match.group(0)), None, None

    reply_user = message.reply_to_message.from_user if message.reply_to_message else None

    if reply_user:
        return reply_user.id, reply_user.username, get_full_name(reply_user)

    return None, None, None


async def friend_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    target_id, username, full_name = _friend_target_from_message(message)

    if not target_id:
        await message.reply_text("Использование: /friend_add 123456789 или reply на сообщение пользователя.")
        return

    set_user_friend(
        settings,
        user_id=target_id,
        is_friend=True,
        username=username,
        full_name=full_name,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="friend_add",
        target=str(target_id),
    )

    await message.reply_text(f"Пользователь {target_id} добавлен в друзья. Реклама ему не показывается.")


async def friend_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    target_id, username, full_name = _friend_target_from_message(message)

    if not target_id:
        await message.reply_text("Использование: /friend_del 123456789 или reply на сообщение пользователя.")
        return

    set_user_friend(
        settings,
        user_id=target_id,
        is_friend=False,
        username=username,
        full_name=full_name,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="friend_del",
        target=str(target_id),
    )

    await message.reply_text(f"Пользователь {target_id} убран из друзей. Реклама снова может показываться.")


async def friend_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    rows = list_friend_users(settings)

    if not rows:
        await message.reply_text("Список друзей пуст.")
        return

    lines = ["Друзья без рекламы:"]

    for row in rows:
        username = f"@{row['username']}" if row["username"] else "-"
        full_name = row["full_name"] or "-"
        lines.append(f"{row['user_id']} | {username} | {full_name}")

    await message.reply_text("\n".join(lines)[:3900])


async def ad_click_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(AD_CLICK_PREFIX):
        return

    try:
        payload = data.replace(AD_CLICK_PREFIX, "", 1)
        parts = payload.split(":", 1)
        ad_id = int(parts[0])
        button_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
    except ValueError:
        await query.answer("Реклама не найдена.", show_alert=True)
        return

    user = update.effective_user
    message = query.message
    chat_id = message.chat_id if message else None
    message_id = message.message_id if message else None

    url = await handle_ad_click(
        context=context,
        ad_id=ad_id,
        button_id=button_id,
        user_id=user.id if user else None,
        chat_id=chat_id,
        message_id=message_id,
    )

    if not url:
        await query.answer("Ссылка недоступна.", show_alert=True)
        return

    await query.answer("Ссылка отправлена.")

    if chat_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Открой ссылку по кнопке ниже.",
            reply_markup=InlineKeyboardMarkup([[
                build_styled_url_button(
                    text="Открыть",
                    url=url,
                    style_config="primary",
                )
            ]]),
            reply_to_message_id=message_id,
            disable_web_page_preview=True,
        )
