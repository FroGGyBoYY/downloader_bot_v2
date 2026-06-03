import csv
import html
import platform as platform_module
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import (
    add_admin,
    get_all_admin_ids,
    is_admin,
    is_base_admin,
    list_dynamic_admins,
    remove_dynamic_admin,
)
from app.db.cookie_auth_repo import log_admin_action, to_local_display
from app.db.database import db_connect
from app.db.user_reports_repo import list_recent_user_reports
from app.db.users_repo import get_full_name, list_banned_users, set_user_banned
from app.services.access_control_service import (
    get_maintenance_text,
    is_maintenance_active,
    set_maintenance,
)
from app.services.daily_report_service import build_daily_admin_report
from app.services.health_service import build_cookie_health_report, build_platform_health_report


ADMIN_FUNCTIONS = [
    (1, "/bot_status", "состояние бота, webhook, БД"),
    (2, "/health_check", "быстрая диагностика окружения"),
    (3, "/users_count", "количество пользователей и активность"),
    (4, "/users_top", "топ пользователей"),
    (5, "/top_downloads", "топ скачиваемых ссылок/видео"),
    (6, "/platform_stats", "статистика по платформам"),
    (7, "/cache_stats", "статистика кеша Telegram file_id"),
    (8, "/errors", "последние ошибки бота и скачиваний"),
    (9, "/recent_downloads", "последние скачивания"),
    (10, "/failed_downloads", "последние неудачные скачивания"),
    (11, "/db_tables", "таблицы БД и количество строк"),
    (12, "/db_export", "выгрузить SQLite базу"),
    (13, "/table_export users", "выгрузить таблицу CSV"),
    (14, "/ad_overview", "сводка по рекламе после выдачи"),
    (15, "/req_overview", "сводка обязательных подписок"),
    (16, "/cookie_check", "состояние cookies"),
    (17, "/admin_list", "список админов"),
    (18, "/admin_add 123456789", "добавить админа"),
    (19, "/admin_del 123456789", "убрать админа из БД"),
    (20, "/friend_list", "друзья без рекламы"),
    (21, "/platform_health", "здоровье платформ за 24 часа"),
    (22, "/cookie_health", "автопроверка активных cookie-слотов"),
    (23, "/daily_report", "ручной ежедневный отчет админу"),
    (24, "/maintenance_on [text]", "включить обслуживание"),
    (25, "/maintenance_off", "выключить обслуживание"),
    (26, "/maintenance_status", "статус обслуживания"),
    (27, "/ban 123456789", "заблокировать пользователя"),
    (28, "/unban 123456789", "разблокировать пользователя"),
    (29, "/banned", "список заблокированных"),
    (30, "/reports", "жалобы пользователей"),
    (31, "/ad8_list", "реклама каждые 8 часов"),
    (32, "/broadcast", "рассылка всем пользователям"),
    (33, "/welcome_status", "приветствие /start и кеш фото"),
    (34, "/cleanup_temp [hours]", "очистка старых временных файлов"),
    (35, "/users", "последние 30 пользователей"),
    (36, "/proxy_list", "активные прокси для YouTube Music"),
    (37, "/proxy_stats", "статистика жизни прокси"),
    (38, "/add_proxy", "добавить один прокси"),
    (39, "/add_proxy_list", "добавить список прокси"),
    (40, "/proxy_hs", "статистика здоровья прокси по странам"),
    (41, "/delete_all_proxy", "удалить все прокси с подтверждением"),
    (42, "/delete_one_proxy 1", "удалить одну прокси по id с подтверждением"),
    (43, "/user 123456789 10", "user downloads history"),
]

ADMIN_RUNNERS = {
    1: "bot_status_cmd",
    2: "health_check_cmd",
    3: "users_count_cmd",
    4: "users_top_cmd",
    5: "top_downloads_cmd",
    6: "platform_stats_cmd",
    7: "cache_stats_cmd",
    8: "errors_cmd",
    9: "recent_downloads_cmd",
    10: "failed_downloads_cmd",
    11: "db_tables_cmd",
    12: "db_export_cmd",
    13: "table_export_cmd",
    14: "ad_overview_cmd",
    15: "req_overview_cmd",
    17: "admin_list_cmd",
    21: "platform_health_cmd",
    22: "cookie_health_cmd",
    23: "daily_report_cmd",
    24: "maintenance_on_cmd",
    25: "maintenance_off_cmd",
    26: "maintenance_status_cmd",
    29: "banned_cmd",
    30: "reports_cmd",
    34: "cleanup_temp_cmd",
    35: "users_cmd",
    40: "proxy_hs_admin_runner",
    41: "delete_all_proxy_admin_runner",
}


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _tail(update: Update) -> str:
    message = update.message

    if not message:
        return ""

    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _deny(update: Update) -> None:
    if update.message:
        await update.message.reply_text("Эта команда доступна только админу.")


async def _ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    user = update.effective_user

    if is_admin(settings, user.id if user else None):
        return True

    await _deny(update)
    return False


def _cut(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[:limit - 20] + "\n...truncated"


async def _reply_text_chunks(message, text: str, *, limit: int = 3900, parse_mode: str | None = None) -> None:
    if not message:
        return

    parts: list[str] = []
    current = ""

    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            parts.append(current)
            current = ""

        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]

        current = line

    if current:
        parts.append(current)

    for part in parts or [text]:
        await message.reply_text(part, parse_mode=parse_mode)


def _parse_limit(raw: str, default: int = 10, maximum: int = 50) -> int:
    raw = raw.strip()

    if not raw:
        return default

    first = raw.split(maxsplit=1)[0]

    try:
        value = int(first)
    except ValueError:
        return default

    return max(1, min(value, maximum))


def _parse_user_and_limit(raw: str, default_limit: int = 10, maximum: int = 200) -> tuple[str | None, int]:
    parts = raw.strip().split()
    if not parts:
        return None, default_limit
    target = parts[0]
    limit = default_limit
    if len(parts) > 1:
        try:
            limit = max(1, min(int(parts[1]), maximum))
        except ValueError:
            limit = default_limit
    return target, limit


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fmt_dt(settings: Settings, value: str | None) -> str:
    return to_local_display(value, settings.local_tz_hours)


def _db_size(path: Path) -> str:
    if not path.exists():
        return "-"

    size = path.stat().st_size

    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024

    return "-"


def _format_bytes(size: int) -> str:
    value = float(max(0, size))

    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024

    return "0 B"


def _entry_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total = 0

    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass

    return total


def _parse_cleanup_hours(raw: str) -> int:
    raw = raw.strip().lower()

    if not raw:
        return 24

    if raw in {"all", "now", "0"}:
        return 0

    try:
        return max(0, int(raw.split(maxsplit=1)[0]))
    except ValueError:
        return 24


def _cleanup_temp_dir(temp_root: Path, older_than_hours: int) -> tuple[int, int, int]:
    temp_root.mkdir(parents=True, exist_ok=True)
    resolved_root = temp_root.resolve()
    cutoff_ts = (
        datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    ).timestamp()
    removed_count = 0
    removed_bytes = 0
    failed_count = 0

    for entry in temp_root.iterdir():
        try:
            resolved_entry = entry.resolve()

            if resolved_root not in (resolved_entry, *resolved_entry.parents):
                failed_count += 1
                continue

            if older_than_hours > 0:
                modified_ts = entry.stat().st_mtime

                if modified_ts > cutoff_ts:
                    continue

            removed_bytes += _entry_size(entry)

            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

            removed_count += 1

        except Exception:
            failed_count += 1

    return removed_count, removed_bytes, failed_count


def _rows_to_lines(rows, formatter) -> list[str]:
    lines = []

    for index, row in enumerate(rows, 1):
        lines.append(formatter(index, row))

    return lines


def _username_label(username: str | None) -> str:
    value = str(username or "").strip()
    if not value:
        return "-"
    return value if value.startswith("@") else f"@{value}"


def _linked_media_label(platform: str | None, content_type: str | None, url: str | None) -> str:
    label = f"{platform or 'unknown'}/{content_type or 'unknown'}"
    safe_label = html.escape(label)
    safe_url = html.escape(str(url or "").strip(), quote=True)
    if not safe_url:
        return safe_label
    return f'<a href="{safe_url}">{safe_label}</a>'


def _download_error_or_title(row) -> str:
    error_type = str(row["error_type"] or "").strip()
    error_text = str(row["error_text"] or "").strip()
    if error_type or error_text:
        if error_type and error_text:
            return f"{error_type}: {error_text}"
        return error_type or error_text
    return str(row["title"] or "-")


def _compact_download_text(value: str | None, limit: int = 220) -> str:
    text = " ".join(str(value or "-").replace("\n", " ").split())
    return text[:limit] or "-"


def _format_recent_download_row(settings: Settings, index: int, row) -> str:
    url = row["original_url"] or row["resolved_url"]
    media_label = _linked_media_label(row["platform"], row["content_type"], url)
    user = html.escape(str(row["user_id"]))
    username = html.escape(_username_label(row["username"]))
    status = html.escape(str(row["status"] or "-"))
    cache_status = html.escape(str(row["cache_status"] or "-"))
    text = html.escape(_compact_download_text(_download_error_or_title(row)))
    return (
        f"{index}. #{row['id']} {html.escape(_fmt_dt(settings, row['created_at']))} | "
        f"user {user} {username} | {media_label} | {status} {cache_status} | "
        f"items {row['items_sent']} | {text}"
    )


def _format_user_download_row(settings: Settings, index: int, row) -> str:
    url = row["original_url"] or row["resolved_url"]
    media_label = _linked_media_label(row["platform"], row["content_type"], url)
    status = html.escape(str(row["status"] or "-"))
    cache_status = html.escape(str(row["cache_status"] or "-"))
    text = html.escape(_compact_download_text(_download_error_or_title(row)))
    return (
        f"{index}. {html.escape(_fmt_dt(settings, row['created_at']))} | "
        f"{media_label} | {status} {cache_status} | "
        f"items {row['items_sent']} | {text}"
    )


def _table_names(settings: Settings) -> list[str]:
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()
    conn.close()
    return [row["name"] for row in rows]


async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    lines = ["Admin panel", "", "Команды пронумерованы:"]

    for number, command, description in ADMIN_FUNCTIONS:
        lines.append(f"{number}. {command} - {description}")

    lines.extend([
        "",
        "Можно быстро вызвать часть команд так: /admin_run 1",
        "Для команд с аргументами используй саму команду из списка.",
        "",
        "Реклама после каждого скачивания:",
        "1. Пришли в чат рекламное сообщение: текст, фото, видео или медиа с caption.",
        "2. Ответь на него командой /ad_add.",
        "3. Без кнопок: /ad_add",
        "4. Одна кнопка: /ad_add Название | https://ссылка | green",
        "5. Несколько кнопок в одной рекламе:",
        "/ad_add 🇰🇿 четкий канал | https://t.me/test_ab_cd | green || 🇯🇵 четкий канал | https://t.me/test_ab_cd | red || 🇯🇵 четкий канал бро | https://t.me/test_ab_cd | black",
        "6. Можно старым способом: reply на рекламу текстом add Название | https://ссылка | green",
        "7. После каждого скачивания отправляются все ACTIVE-рекламы. /ad_off 1 выключает, /ad_on 1 включает.",
        "8. Удалить из текущего списка, но оставить в истории: /ad_del 1.",
        "9. /ad_list показывает только ACTIVE/PAUSED. /ad_stats показывает последние 30 в истории, /ad_stats 1 - подробно.",
        "10. Полная txt-выгрузка всех рекламных кампаний: /ad_stats_txt.",
        "11. Друзья без рекламы: /friend_add, /friend_del, /friend_list.",
        "12. Цвета кнопок Telegram: green, blue, red. black принимается как default/dark, но зависит от клиента Telegram.",
        "",
        "Реклама каждые 8 часов:",
        "1. Пришли рекламное сообщение и ответь на него командой /ad8_add.",
        "2. Без кнопок: /ad8_add",
        "3. Одна кнопка: /ad8_add Название | https://ссылка | green",
        "4. Несколько кнопок:",
        "/ad8_add 🇰🇿 канал | https://t.me/test_ab_cd | green || 🇯🇵 канал | https://t.me/test_ab_cd | red || кнопка | https://t.me/test_ab_cd | black",
        "5. Управление: /ad8_list, /ad8_off 1, /ad8_on 1, /ad8_del 1.",
        "6. Статистика: /ad8_stats, /ad8_stats 1, /ad8_stats_txt.",
        "7. Отправляется всем пользователям, кроме друзей, каждые 8 часов.",
        "",
        "Broadcast:",
        "1. Ответь на любое сообщение командой /broadcast, и бот разошлет его всем пользователям.",
        "2. С кнопками: /broadcast Кнопка | https://url | green || Вторая | https://url | red",
        "3. Короткая команда тоже работает: /bc.",
        "4. Selected users: reply /bc_users 123456789 987654321 [-- Button | https://url | green].",
        "",
        "Приветствие /start:",
        "1. Текст приветствия уже берется из TextKey.START и переведен в ru/en/es/zh/ar/th.",
        "2. Кнопки выбора языка и добавления в группу генерируются ботом автоматически.",
        "3. Чтобы сохранить фото в Telegram file_id: ответь на фото командой /welcome_set.",
        "4. Проверить: /welcome_status. Очистить кеш фото: /welcome_clear.",
        "",
        "Обслуживание файлов:",
        "1. /cleanup_temp удаляет временные файлы старше 24 часов.",
        "2. /cleanup_temp 6 удаляет временные файлы старше 6 часов.",
        "3. /cleanup_temp all удаляет всё в media/temp.",
        "",
        "Обязательные подписки:",
        "1. Публичный канал можно добавить по ссылке, @channel бот возьмет сам:",
        "/req_add channel | 🇮🇳 cool channel 🇿🇲 | https://t.me/test_ab_cd | green",
        "2. Старый формат тоже работает:",
        "/req_add channel @test_ab_cd 🇮🇳 cool channel 🇿🇲 | https://t.me/test_ab_cd | green",
        "3. Приватный канал: нужен chat_id, потому что из invite-ссылки нельзя надежно получить канал для проверки:",
        "/req_add channel -1001234567890 Название | https://t.me/+invite | blue",
        "4. Бот или mini app засчитываются по клику:",
        "/req_add bot @SomeBot Открыть бота | https://t.me/SomeBot | blue",
        "/req_add mini_app Открыть приложение | https://t.me/SomeBot/app | red",
        "5. Текст перед кнопками: /req_text Подпишись, чтобы пользоваться ботом",
        "6. Управление: /req_list, /req_stats 1, /req_off 1, /req_on 1, /req_edit 1 Название | https://url | green",
        "7. Удалить из текущего списка, но оставить историю: /req_del 1.",
        "8. /req_list показывает только ACTIVE/PAUSED. /req_stats показывает последние 30 в истории, /req_stats 1 - подробно.",
        "9. Полная txt-выгрузка всех обязательных ресурсов: /req_list_txt.",
        "10. Helper-бот для проверки канала: добавь checker=helper_1 в конец команды, если настроен токен helper.",
        "",
        "Другие уже существующие команды:",
        "/ccy_1 /ccy_2 /ccy_3 - YouTube cookies",
        "/cct_1 /cct_2 /cct_3 - TikTok cookies",
        "/cci_1 /cci_2 /cci_3 - Instagram cookies",
        "/ccp_1 /ccp_2 /ccp_3 - Pinterest cookies",
        "/ad_add, /ad_del, /ad_list, /ad_stats, /ad_stats_txt, /ad_on, /ad_off",
        "/ad8_add, /ad8_del, /ad8_list, /ad8_stats, /ad8_stats_txt, /ad8_on, /ad8_off",
        "/broadcast или /bc - разослать reply-сообщение всем пользователям",
        "/bc_users 123456789 987654321 - разослать reply-сообщение выбранным пользователям",
        "/welcome_set, /welcome_status, /welcome_clear - приветствие /start",
        "/cleanup_temp [hours|all] - очистка media/temp",
        "/req_add, /req_del, /req_list, /req_list_txt, /req_stats, /req_on, /req_off, /req_checker",
        "/admin_receive_video_on /admin_receive_video_off",
    ])

    await _reply_text_chunks(update.message, "\n".join(lines))


async def admin_run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    tail = _tail(update)

    if not tail.isdigit():
        await update.message.reply_text("Использование: /admin_run 1")
        return

    number = int(tail)
    runner_name = ADMIN_RUNNERS.get(number)

    if not runner_name:
        await update.message.reply_text("Эта функция требует аргументы. Используй команду из /admin.")
        return

    runner = globals().get(runner_name)

    if not runner:
        await update.message.reply_text("Функция не найдена.")
        return

    await runner(update, context)


async def proxy_hs_admin_runner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.handlers.proxies import proxy_hs_cmd

    await proxy_hs_cmd(update, context)


async def delete_all_proxy_admin_runner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.handlers.proxies import delete_all_proxy_cmd

    await delete_all_proxy_cmd(update, context)


async def admin_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    lines = ["Admins", "", "Base admins from nano.env, cannot be removed:"]

    for admin_id in sorted(settings.admin_ids):
        lines.append(f"- {admin_id}")

    lines.append("")
    lines.append("Dynamic admins from DB:")

    dynamic = list_dynamic_admins(settings)

    if not dynamic:
        lines.append("- none")
    else:
        for row in dynamic:
            username = f"@{row['username']}" if row["username"] else "-"
            lines.append(
                f"- {row['user_id']} | {username} | {row['full_name'] or '-'} | "
                f"added {_fmt_dt(settings, row['created_at'])}"
            )

    await update.message.reply_text(_cut("\n".join(lines)))


def _admin_target(update: Update) -> tuple[int | None, str | None, str | None, str | None]:
    message = update.message

    if not message:
        return None, None, None, None

    reply_user = message.reply_to_message.from_user if message.reply_to_message else None

    if reply_user:
        return reply_user.id, reply_user.username, get_full_name(reply_user), _tail(update)

    tail = _tail(update)
    parts = tail.split(maxsplit=1)

    if not parts or not parts[0].isdigit():
        return None, None, None, None

    return int(parts[0]), None, None, parts[1] if len(parts) > 1 else None


async def admin_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    user = update.effective_user
    target_id, username, full_name, note = _admin_target(update)

    if not target_id:
        await update.message.reply_text("Использование: /admin_add 123456789 или reply на сообщение пользователя.")
        return

    add_admin(
        settings,
        user_id=target_id,
        username=username,
        full_name=full_name,
        note=note,
        added_by=user.id if user else None,
    )
    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="admin_add",
        target=str(target_id),
        details=note,
    )

    await update.message.reply_text(f"Админ {target_id} добавлен.")


async def admin_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    user = update.effective_user
    target_id, _, _, _ = _admin_target(update)

    if not target_id:
        await update.message.reply_text("Использование: /admin_del 123456789 или reply на сообщение пользователя.")
        return

    if is_base_admin(settings, target_id):
        await update.message.reply_text("Этого админа нельзя убрать: он прописан в ADMIN_IDS в nano.env.")
        return

    removed = remove_dynamic_admin(settings, user_id=target_id)

    if not removed:
        await update.message.reply_text("Такого динамического админа нет.")
        return

    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="admin_del",
        target=str(target_id),
    )

    await update.message.reply_text(f"Админ {target_id} убран.")


async def bot_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    me = await context.bot.get_me()
    webhook = await context.bot.get_webhook_info()

    conn = db_connect(settings)
    users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    requests = conn.execute("SELECT COUNT(*) AS c FROM download_requests").fetchone()["c"]
    cache_items = conn.execute("SELECT COUNT(*) AS c FROM media_cache").fetchone()["c"]
    errors_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM bot_errors WHERE created_at >= ?",
        (_cutoff(1),),
    ).fetchone()["c"]
    failed_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM download_requests WHERE status = 'failed' AND created_at >= ?",
        (_cutoff(1),),
    ).fetchone()["c"]
    conn.close()

    text = "\n".join([
        "Bot status",
        f"Bot: @{me.username} ({me.id})",
        f"DB: {settings.db_path}",
        f"DB size: {_db_size(settings.db_path)}",
        f"Users: {users}",
        f"Download requests: {requests}",
        f"Cache items: {cache_items}",
        f"Errors 24h: {errors_24h}",
        f"Failed downloads 24h: {failed_24h}",
        f"Daily limit: {settings.daily_limit}",
        f"Maintenance: {'ON' if is_maintenance_active(settings) else 'OFF'}",
        f"Webhook URL: {webhook.url or 'empty'}",
        f"Pending updates: {webhook.pending_update_count}",
        f"Last webhook error: {webhook.last_error_message or 'none'}",
        f"Python: {sys.version.split()[0]}",
        f"OS: {platform_module.platform()}",
    ])

    await update.message.reply_text(_cut(text))


async def health_check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    checks = []

    try:
        conn = db_connect(settings)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks.append("DB: ok")
    except Exception as e:
        checks.append(f"DB: FAIL {type(e).__name__}")

    for binary in ("ffmpeg", "ffprobe", "gallery-dl"):
        checks.append(f"{binary}: {shutil.which(binary) or 'not found'}")

    temp_dir = settings.base_dir / "media" / "temp"
    checks.append(f"temp dir: {'ok' if temp_dir.exists() else 'missing'} ({temp_dir})")
    checks.append(f"helper bots configured: {len(settings.helper_bot_tokens)}")

    conn = db_connect(settings)
    active_ads = conn.execute("SELECT COUNT(*) AS c FROM ad_campaigns WHERE status = 'ACTIVE'").fetchone()["c"]
    active_required = conn.execute("SELECT COUNT(*) AS c FROM required_resources WHERE status = 'ACTIVE'").fetchone()["c"]
    started_stuck = conn.execute("""
        SELECT COUNT(*) AS c
        FROM download_requests
        WHERE status = 'started' AND created_at <= ?
    """, (_cutoff(1),)).fetchone()["c"]
    conn.close()

    checks.append(f"active ads: {active_ads}")
    checks.append(f"active required resources: {active_required}")
    checks.append(f"stuck started requests older 24h: {started_stuck}")

    await update.message.reply_text("Health check\n\n" + "\n".join(checks))


async def cleanup_temp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    hours = _parse_cleanup_hours(_tail(update))
    temp_root = settings.base_dir / "media" / "temp"
    removed_count, removed_bytes, failed_count = _cleanup_temp_dir(temp_root, hours)

    log_admin_action(
        settings,
        admin_id=update.effective_user.id if update.effective_user else None,
        action="cleanup_temp",
        target=str(temp_root),
        details=f"hours={hours} removed={removed_count} bytes={removed_bytes} failed={failed_count}",
    )

    age_text = "all files" if hours == 0 else f"older than {hours}h"
    await update.message.reply_text(
        "Temp cleanup finished\n"
        f"Path: {temp_root}\n"
        f"Mode: {age_text}\n"
        f"Removed items: {removed_count}\n"
        f"Freed: {_format_bytes(removed_bytes)}\n"
        f"Failed items: {failed_count}"
    )


async def users_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    conn = db_connect(settings)
    totals = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN is_friend = 1 THEN 1 ELSE 0 END) AS friends,
            SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END) AS banned,
            SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END) AS active_24h,
            SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END) AS active_7d
        FROM users
    """, (_cutoff(1), _cutoff(7))).fetchone()
    languages = conn.execute("""
        SELECT COALESCE(language_code, '-') AS lang, COUNT(*) AS c
        FROM users
        GROUP BY COALESCE(language_code, '-')
        ORDER BY c DESC
    """).fetchall()
    conn.close()

    lines = [
        "Users",
        f"Total: {totals['total']}",
        f"Friends: {totals['friends'] or 0}",
        f"Banned: {totals['banned'] or 0}",
        f"Active 24h: {totals['active_24h'] or 0}",
        f"Active 7d: {totals['active_7d'] or 0}",
        "",
        "Languages:",
    ]
    lines.extend([f"{row['lang']}: {row['c']}" for row in languages])

    await update.message.reply_text(_cut("\n".join(lines)))


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 30, 100)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            user_id,
            username,
            full_name,
            language_code,
            first_seen,
            last_seen,
            requests_count,
            downloads_count,
            cache_hits_count,
            is_friend,
            is_banned
        FROM users
        ORDER BY first_seen DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    lines = [f"Last users ({len(rows)}/{limit})"]

    if not rows:
        lines.append("No users yet.")

    for index, row in enumerate(rows, 1):
        flags = []

        if row["is_friend"]:
            flags.append("friend")

        if row["is_banned"]:
            flags.append("banned")

        suffix = f" | {', '.join(flags)}" if flags else ""
        username = f"@{row['username']}" if row["username"] else "@-"
        full_name = row["full_name"] or "-"
        lang = row["language_code"] or "-"

        lines.append(
            f"{index}. {row['user_id']} {username} | {full_name} | "
            f"lang {lang} | first {_fmt_dt(settings, row['first_seen'])} | "
            f"last {_fmt_dt(settings, row['last_seen'])} | "
            f"req {row['requests_count']} | dl {row['downloads_count']} | "
            f"cache {row['cache_hits_count']}{suffix}"
        )

    await _reply_text_chunks(update.message, "\n".join(lines))


async def users_top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 10, 50)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT user_id, username, full_name, requests_count, downloads_count, cache_hits_count, last_seen
        FROM users
        ORDER BY downloads_count DESC, requests_count DESC, last_seen DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    lines = ["Top users"]
    lines.extend(_rows_to_lines(
        rows,
        lambda i, row: (
            f"{i}. {row['user_id']} @{row['username'] or '-'} | {row['full_name'] or '-'} | "
            f"downloads {row['downloads_count']} | requests {row['requests_count']} | cache {row['cache_hits_count']}"
        ),
    ))

    await update.message.reply_text(_cut("\n".join(lines)))


async def top_downloads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 10, 50)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            COALESCE(source_key, original_url) AS item_key,
            MAX(title) AS title,
            MAX(platform) AS platform,
            MAX(original_url) AS original_url,
            COUNT(*) AS downloads,
            SUM(CASE WHEN cache_status = 'hit' THEN 1 ELSE 0 END) AS cache_hits
        FROM download_requests
        WHERE status = 'sent'
        GROUP BY COALESCE(source_key, original_url)
        ORDER BY downloads DESC, cache_hits DESC
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        rows = conn.execute("""
            SELECT
                source_key AS item_key,
                MAX(title) AS title,
                MAX(platform) AS platform,
                MAX(original_url) AS original_url,
                SUM(hits) + COUNT(*) AS downloads,
                SUM(hits) AS cache_hits
            FROM media_cache
            GROUP BY source_key
            ORDER BY downloads DESC
            LIMIT ?
        """, (limit,)).fetchall()

    conn.close()

    lines = ["Top downloads"]
    lines.extend(_rows_to_lines(
        rows,
        lambda i, row: (
            f"{i}. {row['title'] or row['item_key']} | {row['platform'] or '-'} | "
            f"downloads {row['downloads']} | cache hits {row['cache_hits'] or 0}\n{row['original_url'] or '-'}"
        ),
    ))

    await update.message.reply_text(_cut("\n\n".join(lines)))


async def platform_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    days = _parse_limit(_tail(update), 30, 365)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            COALESCE(platform, '-') AS platform,
            status,
            COUNT(*) AS c,
            SUM(items_sent) AS items_sent
        FROM download_requests
        WHERE created_at >= ?
        GROUP BY COALESCE(platform, '-'), status
        ORDER BY platform ASC, status ASC
    """, (_cutoff(days),)).fetchall()
    conn.close()

    lines = [f"Platform stats, {days}d"]

    if not rows:
        lines.append("No data yet.")
    else:
        for row in rows:
            lines.append(f"{row['platform']} | {row['status']}: {row['c']} requests, {row['items_sent'] or 0} items")

    await update.message.reply_text(_cut("\n".join(lines)))


async def cache_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    conn = db_connect(settings)
    total = conn.execute("""
        SELECT
            COUNT(*) AS items,
            COUNT(DISTINCT bundle_key) AS bundles,
            SUM(COALESCE(file_size, 0)) AS bytes,
            SUM(hits) AS hits
        FROM media_cache
    """).fetchone()
    by_platform = conn.execute("""
        SELECT COALESCE(platform, '-') AS platform, COUNT(*) AS items, SUM(hits) AS hits
        FROM media_cache
        GROUP BY COALESCE(platform, '-')
        ORDER BY items DESC
    """).fetchall()
    conn.close()

    mb = (total["bytes"] or 0) / 1024 / 1024
    lines = [
        "Cache stats",
        f"Items: {total['items']}",
        f"Bundles: {total['bundles']}",
        f"Approx media bytes: {mb:.1f} MB",
        f"Hits: {total['hits'] or 0}",
        "",
        "By platform:",
    ]
    lines.extend([f"{row['platform']}: items {row['items']}, hits {row['hits'] or 0}" for row in by_platform])

    await update.message.reply_text(_cut("\n".join(lines)))


async def errors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 10, 30)
    conn = db_connect(settings)
    bot_errors = conn.execute("""
        SELECT *
        FROM bot_errors
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    failed_downloads = conn.execute("""
        SELECT id, user_id, platform, title, error_type, error_text, created_at
        FROM download_requests
        WHERE status = 'failed'
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    lines = ["Errors", "", "Unhandled handler errors:"]

    if not bot_errors:
        lines.append("- none")
    else:
        lines.extend(_rows_to_lines(
            bot_errors,
            lambda i, row: f"{i}. {_fmt_dt(settings, row['created_at'])} | {row['error_type']} | user {row['user_id']} | {row['error_text']}",
        ))

    lines.extend(["", "Failed downloads:"])

    if not failed_downloads:
        lines.append("- none")
    else:
        lines.extend(_rows_to_lines(
            failed_downloads,
            lambda i, row: f"{i}. #{row['id']} {_fmt_dt(settings, row['created_at'])} | {row['platform']} | user {row['user_id']} | {row['error_type']}: {row['error_text']}",
        ))

    await update.message.reply_text(_cut("\n".join(lines)))


async def recent_downloads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 10, 200)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            r.id,
            r.user_id,
            COALESCE(r.username, u.username) AS username,
            r.platform,
            r.content_type,
            r.title,
            r.status,
            r.cache_status,
            r.items_sent,
            r.original_url,
            r.resolved_url,
            r.error_type,
            r.error_text,
            r.created_at
        FROM download_requests r
        LEFT JOIN users u ON u.user_id = r.user_id
        ORDER BY r.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    lines = ["Recent downloads"]
    lines.extend(_rows_to_lines(
        rows,
        lambda i, row: _format_recent_download_row(settings, i, row),
    ))

    await _reply_text_chunks(update.message, "\n".join(lines), parse_mode="HTML")


async def user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    target, limit = _parse_user_and_limit(_tail(update), 10, 200)

    if not target:
        await update.message.reply_text("Usage: /user 123456789 10 or /user @username 10")
        return

    conn = db_connect(settings)

    if target.startswith("@"):
        username = target[1:].strip().lower()
        user = conn.execute(
            """
            SELECT user_id, username, full_name
            FROM users
            WHERE lower(username) = ?
            LIMIT 1
            """,
            (username,),
        ).fetchone()

        if not user:
            user = conn.execute(
                """
                SELECT user_id, username, full_name
                FROM download_requests
                WHERE lower(username) = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (username,),
            ).fetchone()
    else:
        try:
            user_id = int(target)
        except ValueError:
            user_id = 0

        user = conn.execute(
            """
            SELECT user_id, username, full_name
            FROM users
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if not user and user_id:
            user = conn.execute(
                """
                SELECT user_id, username, full_name
                FROM download_requests
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

    if not user:
        conn.close()
        await update.message.reply_text("User not found.")
        return

    rows = conn.execute(
        """
        SELECT
            r.id,
            r.user_id,
            COALESCE(r.username, u.username) AS username,
            r.platform,
            r.content_type,
            r.title,
            r.status,
            r.cache_status,
            r.items_sent,
            r.original_url,
            r.resolved_url,
            r.error_type,
            r.error_text,
            r.created_at
        FROM download_requests r
        LEFT JOIN users u ON u.user_id = r.user_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT ?
        """,
        (user["user_id"], limit),
    ).fetchall()
    conn.close()

    username_label = _username_label(user["username"])
    full_name = user["full_name"] or "-"
    lines = [
        f"User {html.escape(str(user['user_id']))} {html.escape(username_label)} | {html.escape(full_name)}",
        f"Recent downloads ({len(rows)}/{limit})",
    ]

    if not rows:
        lines.append("No downloads.")
    else:
        lines.extend(_rows_to_lines(
            rows,
            lambda i, row: _format_user_download_row(settings, i, row),
        ))

    await _reply_text_chunks(update.message, "\n".join(lines), parse_mode="HTML")


async def failed_downloads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    limit = _parse_limit(_tail(update), 10, 50)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT id, user_id, platform, title, original_url, error_type, error_text, created_at
        FROM download_requests
        WHERE status = 'failed'
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    lines = ["Failed downloads"]

    if not rows:
        lines.append("No failed downloads.")
    else:
        lines.extend(_rows_to_lines(
            rows,
            lambda i, row: (
                f"{i}. #{row['id']} {_fmt_dt(settings, row['created_at'])} | user {row['user_id']} | {row['platform']} | "
                f"{row['error_type']}: {row['error_text']}\n{row['original_url']}"
            ),
        ))

    await update.message.reply_text(_cut("\n\n".join(lines)))


async def db_tables_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    conn = db_connect(settings)
    lines = ["DB tables"]

    for table in _table_names(settings):
        count = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        lines.append(f"{table}: {count}")

    conn.close()
    await update.message.reply_text(_cut("\n".join(lines)))


async def db_export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    temp_root = settings.base_dir / "media" / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_path = temp_root / f"bot_db_export_{timestamp}.db"

    source = sqlite3.connect(settings.db_path)
    target = sqlite3.connect(export_path)
    source.backup(target)
    target.close()
    source.close()

    with open(export_path, "rb") as file_obj:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_obj,
            filename=export_path.name,
            caption=f"DB export: {_db_size(export_path)}",
        )


async def table_export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    table = (_tail(update).split(maxsplit=1)[0] if _tail(update) else "").strip()

    if not table:
        await update.message.reply_text("Использование: /table_export users")
        return

    allowed = set(_table_names(settings))

    if table not in allowed:
        await update.message.reply_text("Такой таблицы нет. Используй /db_tables.")
        return

    temp_root = settings.base_dir / "media" / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_path = temp_root / f"{table}_{timestamp}.csv"

    conn = db_connect(settings)
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    columns = [description[0] for description in conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
    conn.close()

    with open(export_path, "w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[column] for column in columns])

    with open(export_path, "rb") as file_obj:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_obj,
            filename=export_path.name,
            caption=f"Table export: {table}, rows {len(rows)}",
        )


async def ad_overview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT id, status, source_type, button_text, impressions_count, clicks_count, blocked_count, failed_count
        FROM ad_campaigns
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    lines = ["Ads overview"]

    if not rows:
        lines.append("No ads.")
    else:
        lines.extend(_rows_to_lines(
            rows,
            lambda i, row: (
                f"{i}. #{row['id']} {row['status']} | {row['source_type'] or '-'} | "
                f"views {row['impressions_count']} | clicks {row['clicks_count']} | "
                f"blocked {row['blocked_count']} | failed {row['failed_count']} | {row['button_text'] or '-'}"
            ),
        ))

    await update.message.reply_text(_cut("\n".join(lines)))


async def req_overview_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT id, status, resource_type, target_chat, checker_bot_key, button_text,
               impressions_count, clicks_count, passes_count, fails_count, check_errors_count
        FROM required_resources
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    lines = ["Required subscriptions overview"]

    if not rows:
        lines.append("No required resources.")
    else:
        lines.extend(_rows_to_lines(
            rows,
            lambda i, row: (
                f"{i}. #{row['id']} {row['status']} | {row['resource_type']} | {row['target_chat'] or '-'} | "
                f"checker {row['checker_bot_key']} | views {row['impressions_count']} | clicks {row['clicks_count']} | "
                f"pass {row['passes_count']} | fail {row['fails_count']} | errors {row['check_errors_count']} | "
                f"{row['button_text']}"
            ),
        ))

    await update.message.reply_text(_cut("\n".join(lines)))


async def platform_health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    await update.message.reply_text(_cut(build_platform_health_report(settings)))


async def cookie_health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    text, _ = build_cookie_health_report(settings, only_problems=False)
    await update.message.reply_text(_cut(text))


async def daily_report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    await update.message.reply_text(_cut(build_daily_admin_report(settings)))


async def maintenance_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    user = update.effective_user
    text = _tail(update) or settings.maintenance_default_text
    set_maintenance(settings, enabled=True, text=text)
    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="maintenance_on",
        details=text,
    )
    await update.message.reply_text(f"Maintenance включен.\n\nТекст: {text}")


async def maintenance_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    user = update.effective_user
    set_maintenance(settings, enabled=False)
    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="maintenance_off",
    )
    await update.message.reply_text("Maintenance выключен.")


async def maintenance_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    state = "ON" if is_maintenance_active(settings) else "OFF"
    await update.message.reply_text(
        f"Maintenance: {state}\n\nТекст: {get_maintenance_text(settings)}"
    )


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    admin = update.effective_user
    target_id, username, full_name, _ = _admin_target(update)

    if not target_id:
        await update.message.reply_text("Использование: /ban 123456789 или reply на сообщение пользователя.")
        return

    if is_admin(settings, target_id):
        await update.message.reply_text("Админа нельзя забанить через эту команду.")
        return

    set_user_banned(
        settings,
        user_id=target_id,
        is_banned=True,
        username=username,
        full_name=full_name,
    )
    log_admin_action(
        settings,
        admin_id=admin.id if admin else None,
        action="user_ban",
        target=str(target_id),
    )
    await update.message.reply_text(f"Пользователь {target_id} заблокирован.")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    admin = update.effective_user
    target_id, username, full_name, _ = _admin_target(update)

    if not target_id:
        await update.message.reply_text("Использование: /unban 123456789 или reply на сообщение пользователя.")
        return

    set_user_banned(
        settings,
        user_id=target_id,
        is_banned=False,
        username=username,
        full_name=full_name,
    )
    log_admin_action(
        settings,
        admin_id=admin.id if admin else None,
        action="user_unban",
        target=str(target_id),
    )
    await update.message.reply_text(f"Пользователь {target_id} разблокирован.")


async def banned_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    rows = list_banned_users(settings)
    lines = ["Banned users"]

    if not rows:
        lines.append("No banned users.")
    else:
        for row in rows[:50]:
            lines.append(
                f"- {row['user_id']} @{row['username'] or '-'} | "
                f"{row['full_name'] or '-'} | last {_fmt_dt(settings, row['last_seen'])}"
            )

    await update.message.reply_text(_cut("\n".join(lines)))


async def reports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return

    settings = _settings(context)
    rows = list_recent_user_reports(settings, limit=20)
    lines = ["User reports"]

    if not rows:
        lines.append("No reports yet.")
    else:
        for row in rows:
            lines.append(
                f"#{row['id']} {_fmt_dt(settings, row['created_at'])} | "
                f"user {row['user_id']} @{row['username'] or '-'} | {row['status']}\n"
                f"{str(row['report_text'])[:500]}"
            )

    await update.message.reply_text(_cut("\n\n".join(lines)))
