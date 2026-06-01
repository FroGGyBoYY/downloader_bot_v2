import csv
import re
import tempfile
from urllib.parse import urlparse

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.cookie_auth_repo import log_admin_action, to_local_display
from app.db.database import db_connect
from app.db.users_repo import get_user_language
from app.db.required_subscriptions_repo import (
    ACTIVE,
    DELETED,
    PAUSED,
    RESOURCE_TYPES,
    create_required_resource,
    get_required_resource,
    get_required_subscriptions_text,
    get_required_unique_event_counts,
    list_current_required_resources,
    list_required_resources,
    set_required_resource_status,
    set_required_subscriptions_text,
    update_required_resource_button,
    update_required_resource_checker,
)
from app.services.required_subscriptions_service import (
    REQUIRED_CHECK_CALLBACK,
    REQUIRED_OPEN_PREFIX,
    open_required_resource,
    refresh_required_subscriptions_message,
)
from app.telegram_ui.button_styles import build_styled_url_button
from app.texts.keys import TextKey
from app.texts.renderer import render_text


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return is_admin(settings, user_id)


def _language_for_user(settings: Settings, user_id: int | None) -> str | None:
    if not user_id:
        return None

    try:
        return get_user_language(settings, user_id)
    except Exception:
        return None


def _plain_text(key: str, language_code: str | None = None, **variables) -> str:
    text, _ = render_text(key, language_code=language_code, **variables)
    return text


def _tail(update: Update) -> str:
    message = update.message

    if not message:
        return ""

    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _command_name(update: Update) -> str:
    message = update.message

    if not message:
        return ""

    return (message.text or "").split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()


def _valid_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _public_tme_username(value: str) -> str | None:
    value = value.strip()

    if value.startswith("@"):
        username = value[1:]
    else:
        parsed = urlparse(value)

        if parsed.netloc.lower() not in {"t.me", "telegram.me"}:
            return None

        parts = [part for part in parsed.path.strip("/").split("/") if part]

        if not parts or parts[0] in {"c", "joinchat", "+"}:
            return None

        username = parts[0]

    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", username):
        return None

    return username


def _normalize_channel_target(raw: str) -> tuple[str | None, str | None]:
    raw = raw.strip()

    if re.fullmatch(r"-?\d+", raw):
        return raw, None

    username = _public_tme_username(raw)

    if username:
        return f"@{username}", f"https://t.me/{username}"

    return None, None


def _normalize_bot_target(raw: str) -> tuple[str | None, str | None]:
    username = _public_tme_username(raw)

    if username:
        return f"@{username}", f"https://t.me/{username}"

    return None, None


def _extract_url(raw: str) -> str | None:
    match = re.search(r"https?://\S+", raw)
    return match.group(0).rstrip(".,);]}>") if match else None


def _parse_button_config(
    raw: str,
    *,
    default_text: str | None,
    default_url: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    raw = raw.strip()

    if raw.startswith("|"):
        raw = raw[1:].strip()

    if not raw:
        if default_text and default_url:
            return default_text[:64], default_url, None, None

        return None, None, None, "Укажи кнопку: Название | https://ссылка"

    parts = [part.strip() for part in raw.split("|")]

    if len(parts) >= 2:
        button_text = parts[0] or default_text or "Открыть"
        button_url = parts[1] or default_url
        button_style = parts[2] if len(parts) >= 3 and parts[2] else None

        if not button_url or not _valid_url(button_url):
            return None, None, None, "Ссылка кнопки должна начинаться с http:// или https://."

        return button_text[:64], button_url, button_style, None

    found_url = _extract_url(raw)

    if found_url:
        button_text = raw.replace(found_url, "").strip() or default_text or "Открыть"
        return button_text[:64], found_url, None, None

    if default_url:
        return raw[:64], default_url, None, None

    return None, None, None, "Укажи ссылку кнопки: Название | https://ссылка"


def _parse_checker_config(raw: str, settings: Settings) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in raw.split("|")]
    kept = []
    checker_bot_key = "main"

    for part in parts:
        if part.lower().startswith("checker="):
            checker_bot_key = part.split("=", 1)[1].strip().lower() or "main"
            continue

        kept.append(part)

    if checker_bot_key != "main" and checker_bot_key not in settings.helper_bot_tokens:
        available = ", ".join(["main", *sorted(settings.helper_bot_tokens)])
        return " | ".join(kept).strip(), checker_bot_key, f"Checker {checker_bot_key} не настроен. Доступно: {available}"

    return " | ".join(kept).strip(), checker_bot_key, None


def _parse_req_add(raw: str, settings: Settings) -> tuple[dict | None, str | None]:
    if not raw:
        return None, (
            "Использование:\n"
            "/req_add channel | Название кнопки | https://t.me/channel | green\n"
            "/req_add channel @channel Название | https://t.me/channel | green\n"
            "/req_add bot @SomeBot Название | https://t.me/SomeBot\n"
            "/req_add mini_app Название | https://t.me/bot/app"
        )

    first = raw.split(maxsplit=1)
    resource_type = first[0].lower().strip()
    rest = first[1].strip() if len(first) > 1 else ""

    if resource_type not in RESOURCE_TYPES:
        return None, "Тип должен быть channel, bot, mini_app или link."

    target_chat = None
    checker_bot_key = "main"
    default_text = None
    default_url = None
    config = rest

    if resource_type == "channel":
        if rest.lstrip().startswith("|"):
            config, checker_bot_key, checker_error = _parse_checker_config(rest, settings)

            if checker_error:
                return None, checker_error

            button_text, button_url, button_style, error = _parse_button_config(
                config,
                default_text=None,
                default_url=None,
            )

            if error:
                return None, error

            target_chat, _ = _normalize_channel_target(button_url or "")

            if not target_chat:
                return None, "Не смог взять @channel из ссылки. Для приватного канала используй старый формат: /req_add channel -1001234567890 Название | https://ссылка"

            return {
                "resource_type": resource_type,
                "target_chat": target_chat,
                "checker_bot_key": checker_bot_key,
                "button_text": button_text,
                "button_url": button_url,
                "button_style": button_style,
            }, None

        else:
            parts = rest.split(maxsplit=1)

            if not parts:
                return None, "Для channel укажи @channel/chat_id или новый формат: /req_add channel | Кнопка | https://t.me/channel | green"

            target_chat, default_url = _normalize_channel_target(parts[0])

            if not target_chat:
                return None, "Не понял канал. Для публичного канала используй ссылку https://t.me/channel или @channel, для приватного - chat_id."

            default_text = target_chat
            config = parts[1].strip() if len(parts) > 1 else ""
            config, checker_bot_key, checker_error = _parse_checker_config(config, settings)

            if checker_error:
                return None, checker_error

    elif resource_type == "bot":
        parts = rest.split(maxsplit=1)

        if not parts:
            return None, "Для bot укажи @bot или кнопку со ссылкой."

        target_chat, default_url = _normalize_bot_target(parts[0])

        if target_chat:
            default_text = target_chat
            config = parts[1].strip() if len(parts) > 1 else ""
        else:
            default_text = "Открыть бота"
            config = rest

    else:
        default_text = "Открыть"
        config = rest

    button_text, button_url, button_style, error = _parse_button_config(
        config,
        default_text=default_text,
        default_url=default_url,
    )

    if error:
        return None, error

    return {
        "resource_type": resource_type,
        "target_chat": target_chat,
        "checker_bot_key": checker_bot_key,
        "button_text": button_text,
        "button_url": button_url,
        "button_style": button_style,
    }, None


def _format_required_brief(row) -> str:
    return (
        f"#{row['id']} | {row['status']} | {row['resource_type']} | "
        f"показы {row['impressions_count']} | клики {row['clicks_count']} | "
        f"pass {row['passes_count']} | fail {row['fails_count']} | ошибки {row['check_errors_count']}"
    )


async def _send_required_resources_txt(message, settings: Settings) -> None:
    temp_root = settings.base_dir / "media" / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)

    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM required_resources
        ORDER BY id DESC
    """).fetchall()
    conn.close()

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        suffix="_required_resources.txt",
        dir=temp_root,
        delete=False,
    ) as fp:
        path = fp.name
        writer = csv.writer(fp, delimiter="\t")
        columns = [
            "id",
            "status",
            "resource_type",
            "target_chat",
            "checker_bot_key",
            "button_text",
            "button_url",
            "button_style",
            "impressions_count",
            "clicks_count",
            "passes_count",
            "fails_count",
            "check_errors_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
        writer.writerow(columns)

        for row in rows:
            writer.writerow([(row[column] if row[column] is not None else "") for column in columns])

    with open(path, "rb") as document:
        await message.reply_document(
            document=document,
            filename="required_resources.txt",
            caption=f"Выгрузка обязательных ресурсов: {len(rows)} строк.",
        )


def _find_existing_required_channel(settings: Settings, target_chat: str | None):
    if not target_chat:
        return None

    normalized = str(target_chat).strip().lower()

    for row in list_required_resources(settings, active_only=False, limit=500):
        if row["status"] not in {ACTIVE, PAUSED}:
            continue

        if str(row["resource_type"] or "").lower() != "channel":
            continue

        if str(row["target_chat"] or "").strip().lower() == normalized:
            return row

    return None


async def req_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    data, error = _parse_req_add(_tail(update), settings)

    if error or not data:
        await message.reply_text(error or "Не понял команду.")
        return

    if data["resource_type"] == "channel":
        existing = _find_existing_required_channel(settings, data["target_chat"])

        if existing:
            await message.reply_text(
                f"Этот канал уже есть в обязательных ресурсах: #{existing['id']} ({existing['status']}).\n"
                f"Target: {existing['target_chat']}\n\n"
                "Дубль не добавляю, иначе две кнопки будут проверять один и тот же канал."
            )
            return

    resource_id = create_required_resource(
        settings,
        resource_type=data["resource_type"],
        target_chat=data["target_chat"],
        checker_bot_key=data["checker_bot_key"],
        button_text=data["button_text"],
        button_url=data["button_url"],
        button_style=data["button_style"],
        created_by=user.id if user else None,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_resource_create",
        target=str(resource_id),
        details=f"type={data['resource_type']} target={data['target_chat'] or '-'} checker={data['checker_bot_key']}",
    )

    lines = [
        f"Обязательный ресурс #{resource_id} добавлен.",
        f"Тип: {data['resource_type']}",
        f"Кнопка: {data['button_text']}",
    ]

    if data["resource_type"] == "channel":
        lines.append("Проверка подписки будет автоматической через Telegram.")
        lines.append(f"Checker: {data['checker_bot_key']}")
    else:
        lines.append("Этот тип Telegram напрямую не проверяет, он будет засчитываться после нажатия кнопки.")

    if data["button_style"]:
        lines.append("Стиль кнопки будет применен в Telegram-кнопке.")

    await message.reply_text("\n".join(lines))


async def req_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    rows = list_current_required_resources(settings)

    if not rows:
        await message.reply_text("Активных или поставленных на паузу обязательных ресурсов пока нет.")
        return

    lines = ["Обязательные ресурсы: текущие ACTIVE/PAUSED"]

    for row in rows:
        lines.append(
            f"#{row['id']} | {row['status']} | {row['resource_type']} | "
            f"checker {row['checker_bot_key']} | {row['button_text']} | показы {row['impressions_count']} | клики {row['clicks_count']} | "
            f"pass {row['passes_count']} | fail {row['fails_count']}"
        )

    await message.reply_text("\n".join(lines)[:3900])


async def req_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _tail(update)

    if not tail.isdigit():
        await message.reply_text("Использование: /req_del 1")
        return

    resource_id = int(tail)

    if not set_required_resource_status(settings, resource_id, DELETED):
        await message.reply_text("Такого обязательного ресурса нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_resource_delete",
        target=str(resource_id),
        details="soft_delete",
    )

    await message.reply_text(f"Обязательный ресурс #{resource_id} удален из текущего списка, но сохранен в истории.")


async def req_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _tail(update)

    if not tail:
        rows = list_required_resources(settings, active_only=False, limit=30)

        if not rows:
            await message.reply_text("Истории обязательных ресурсов пока нет.")
            return

        lines = ["История обязательных ресурсов: последние 30"]

        for row in rows:
            lines.append(_format_required_brief(row))

        lines.append("")
        lines.append("Подробно по ресурсу: /req_stats 1")
        lines.append("Полная выгрузка: /req_list_txt")
        await message.reply_text("\n".join(lines)[:3900])
        return

    if not tail.isdigit():
        await message.reply_text("Использование: /req_stats или /req_stats 1")
        return

    row = get_required_resource(settings, int(tail))

    if not row:
        await message.reply_text("Такого обязательного ресурса нет.")
        return

    unique = get_required_unique_event_counts(settings, int(row["id"]))

    lines = [
        f"Обязательный ресурс #{row['id']}",
        f"Статус: {row['status']}",
        f"Тип: {row['resource_type']}",
        f"Target: {row['target_chat'] or '-'}",
        f"Checker: {row['checker_bot_key']}",
        f"Кнопка: {row['button_text']}",
        f"URL: {row['button_url']}",
        f"Показы: {row['impressions_count']} / уник. {unique.get('impression', 0)}",
        f"Клики: {row['clicks_count']} / уник. {unique.get('click', 0)}",
        f"Успешные проверки: {row['passes_count']} / уник. {unique.get('pass', 0)}",
        f"Не прошли проверку: {row['fails_count']} / уник. {unique.get('fail', 0)}",
        f"Ошибки проверки: {row['check_errors_count']} / уник. {unique.get('check_error', 0)}",
        f"Создан: {to_local_display(row['created_at'], settings.local_tz_hours)}",
        f"Обновлен: {to_local_display(row['updated_at'], settings.local_tz_hours)}",
    ]

    await message.reply_text("\n".join(lines)[:3900])


async def req_list_txt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    await _send_required_resources_txt(message, settings)


async def req_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    command = _command_name(update)
    status = ACTIVE if command == "req_on" else PAUSED
    tail = _tail(update)

    if not tail.isdigit():
        await message.reply_text(f"Использование: /{command} 1")
        return

    resource_id = int(tail)

    if not set_required_resource_status(settings, resource_id, status):
        await message.reply_text("Такого обязательного ресурса нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_resource_status",
        target=str(resource_id),
        details=status,
    )

    await message.reply_text(f"Обязательный ресурс #{resource_id}: {status}.")


async def req_edit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    tail = _tail(update)
    parts = tail.split(maxsplit=1)

    if len(parts) < 2 or not parts[0].isdigit():
        await message.reply_text("Использование: /req_edit 1 Название | https://url")
        return

    resource_id = int(parts[0])
    resource = get_required_resource(settings, resource_id)

    if not resource:
        await message.reply_text("Такого обязательного ресурса нет.")
        return

    button_text, button_url, button_style, error = _parse_button_config(
        parts[1],
        default_text=resource["button_text"],
        default_url=resource["button_url"],
    )

    if error:
        await message.reply_text(error)
        return

    update_required_resource_button(
        settings,
        resource_id=resource_id,
        button_text=button_text,
        button_url=button_url,
        button_style=button_style,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_resource_edit",
        target=str(resource_id),
        details=f"button={button_text}",
    )

    await message.reply_text(f"Кнопка обязательного ресурса #{resource_id} обновлена.")


async def req_checker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    parts = _tail(update).split(maxsplit=1)

    if len(parts) != 2 or not parts[0].isdigit():
        available = ", ".join(["main", *sorted(settings.helper_bot_tokens)])
        await message.reply_text(f"Использование: /req_checker 1 helper_1\nДоступно: {available}")
        return

    resource_id = int(parts[0])
    checker_bot_key = parts[1].strip().lower()

    if checker_bot_key != "main" and checker_bot_key not in settings.helper_bot_tokens:
        available = ", ".join(["main", *sorted(settings.helper_bot_tokens)])
        await message.reply_text(f"Checker {checker_bot_key} не настроен. Доступно: {available}")
        return

    resource = get_required_resource(settings, resource_id)

    if not resource:
        await message.reply_text("Такого обязательного ресурса нет.")
        return

    if resource["resource_type"] != "channel" and checker_bot_key != "main":
        await message.reply_text("Helper-checker нужен только для channel. Bot/mini_app засчитываются по клику.")
        return

    update_required_resource_checker(
        settings,
        resource_id=resource_id,
        checker_bot_key=checker_bot_key,
    )

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_resource_checker",
        target=str(resource_id),
        details=checker_bot_key,
    )

    await message.reply_text(f"Checker обязательного ресурса #{resource_id}: {checker_bot_key}.")


async def req_text_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    text = _tail(update)

    if not text:
        await message.reply_text(get_required_subscriptions_text(settings))
        return

    set_required_subscriptions_text(settings, text[:3000])
    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="required_text_set",
        target="required_subscriptions_text",
    )
    await message.reply_text("Текст обязательной подписки обновлен.")


async def required_open_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(REQUIRED_OPEN_PREFIX):
        return

    try:
        resource_id = int(data.replace(REQUIRED_OPEN_PREFIX, "", 1))
    except ValueError:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, update.effective_user.id if update.effective_user else None)
        await query.answer(_plain_text(TextKey.REQUIRED_RESOURCE_NOT_FOUND, lang), show_alert=True)
        return

    user = update.effective_user
    message = query.message
    chat_id = message.chat_id if message else None
    settings: Settings = context.application.bot_data["settings"]
    lang = _language_for_user(settings, user.id if user else None)

    url = await open_required_resource(
        context=context,
        resource_id=resource_id,
        user_id=user.id if user else None,
        chat_id=chat_id,
    )

    if not url:
        await query.answer(_plain_text(TextKey.REQUIRED_URL_UNAVAILABLE, lang), show_alert=True)
        return

    await query.answer(_plain_text(TextKey.REQUIRED_URL_SENT, lang))

    if not message:
        return

    resource = get_required_resource(settings, resource_id)
    button_text = str(resource["button_text"] or "Открыть ресурс") if resource else "Открыть ресурс"
    button_style = str(resource["button_style"] or "primary") if resource else "primary"

    await context.bot.send_message(
        chat_id=message.chat_id,
        text=_plain_text(TextKey.REQUIRED_OPEN_PROMPT, lang),
        reply_markup=InlineKeyboardMarkup([[
            build_styled_url_button(
                text=button_text,
                url=url,
                style_config=button_style,
            )
        ]]),
        reply_to_message_id=message.message_id,
        disable_web_page_preview=True,
    )


async def required_check_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if not query or not query.message:
        return

    user = update.effective_user
    message = query.message

    complete = await refresh_required_subscriptions_message(
        context=context,
        chat_id=message.chat_id,
        user_id=user.id if user else None,
        message_id=message.message_id,
    )

    if complete:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, user.id if user else None)
        await query.answer(_plain_text(TextKey.REQUIRED_DONE, lang))
    else:
        settings: Settings = context.application.bot_data["settings"]
        lang = _language_for_user(settings, user.id if user else None)
        await query.answer(_plain_text(TextKey.REQUIRED_SUBSCRIPTION_NOT_FOUND, lang), show_alert=True)
