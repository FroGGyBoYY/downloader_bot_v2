from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.proxy_pool_repo import (
    add_proxies,
    backfill_proxy_countries,
    delete_all_proxies,
    delete_proxy_by_id,
    get_proxy_by_id,
    list_proxies,
    mask_proxy,
    parse_proxy_payload,
    proxy_counts,
    proxy_health_stats,
    proxy_stats,
)


PROXY_DELETE_CONFIRM_PREFIX = "proxy_delete:"


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _command_tail(update: Update) -> str:
    message = update.message
    if not message:
        return ""
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _proxy_full_line(row: dict) -> str:
    country = str(row.get("country_code") or "??").upper()
    status = str(row.get("status") or "-")
    return "#{id} {country} {status} {proxy} | req={req} ok={ok} fail={fail}".format(
        id=row.get("id"),
        country=country,
        status=status,
        proxy=str(row.get("proxy_url") or ""),
        req=int(row.get("requests_count") or 0),
        ok=int(row.get("success_count") or 0),
        fail=int(row.get("fail_count") or 0),
    )


def _confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да", callback_data=f"{PROXY_DELETE_CONFIRM_PREFIX}{action}:yes"),
                InlineKeyboardButton("Нет", callback_data=f"{PROXY_DELETE_CONFIRM_PREFIX}{action}:no"),
            ]
        ]
    )


def _download_document_via_telegram_api(settings: Settings, file_id: str, path: Path) -> None:
    token = str(settings.bot_token or "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is empty")

    get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={quote(file_id, safe='')}"
    with urlopen(get_file_url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    if not isinstance(payload, dict) or not payload.get("ok"):
        description = payload.get("description") if isinstance(payload, dict) else payload
        raise RuntimeError(str(description))

    result = payload.get("result")
    if not isinstance(result, dict) or not result.get("file_path"):
        raise RuntimeError("Telegram did not return file_path")

    file_url = f"https://api.telegram.org/file/bot{token}/{result['file_path']}"
    with urlopen(file_url, timeout=30) as response:
        path.write_bytes(response.read())


async def _ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    user = update.effective_user
    if is_admin(settings, user.id if user else None):
        return True
    if update.message:
        await update.message.reply_text("Эта команда доступна только админу.")
    return False


async def _read_proxy_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    message = update.message
    if not message:
        return None

    tail = _command_tail(update)
    if tail:
        return tail

    reply = message.reply_to_message
    if not reply:
        await message.reply_text(
            "Пришли прокси после команды или ответь командой на сообщение/файл со списком прокси."
        )
        return None

    if reply.document:
        settings = _settings(context)
        temp_root = settings.base_dir / "media" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmpdir:
            path = Path(tmpdir) / "proxies.txt"
            try:
                tg_file = await context.bot.get_file(reply.document.file_id)
                await tg_file.download_to_drive(custom_path=path)
            except (TelegramError, RuntimeError) as error:
                try:
                    await asyncio.to_thread(
                        _download_document_via_telegram_api,
                        settings,
                        reply.document.file_id,
                        path,
                    )
                except Exception as fallback_error:
                    await message.reply_text(
                        "Не смог прочитать файл с прокси.\n"
                        f"Telegram: {error}\n"
                        f"Fallback: {fallback_error}\n\n"
                        "Быстрый обход: отправь список обычным текстом и ответь на него /add_proxy_list."
                    )
                    return None
            return path.read_text(encoding="utf-8", errors="replace")

    text = reply.text or reply.caption
    if text:
        return text

    await message.reply_text("В reply должен быть текст или файл со списком прокси.")
    return None


async def add_proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _add_proxy_common(update, context, list_mode=False)


async def add_proxy_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _add_proxy_common(update, context, list_mode=True)


async def _add_proxy_common(update: Update, context: ContextTypes.DEFAULT_TYPE, *, list_mode: bool) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    payload = await _read_proxy_payload(update, context)
    if payload is None:
        return

    proxies = parse_proxy_payload(payload)
    if not proxies:
        await message.reply_text(
            "Не нашел прокси. Форматы: host:port:user:pass, host:port или http://user:pass@host:port"
        )
        return
    if not list_mode:
        proxies = proxies[:1]

    user = update.effective_user
    added, reactivated = add_proxies(_settings(context), proxies, admin_id=user.id if user else None)
    counts = proxy_counts(_settings(context))
    await message.reply_text(
        "Прокси добавлены.\n"
        f"Новых: {added}\n"
        f"Вернул в ACTIVE: {reactivated}\n"
        f"Активных сейчас: {counts['active']}\n"
        f"Мертвых в истории: {counts['dead']}"
    )


async def proxy_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    rows = list_proxies(_settings(context), include_dead=False)
    if not rows:
        await message.reply_text("Активных прокси нет. Добавь через /add_proxy_list.")
        return

    lines = [f"Активных прокси: {len(rows)}", ""]
    for row in rows[:80]:
        country = str(row.get("country_code") or "??").upper()
        lines.append(
            "#{id} {country} {proxy} | req={req} ok={ok} fail={fail}".format(
                id=row["id"],
                country=country,
                proxy=mask_proxy(str(row["proxy_url"])),
                req=int(row["requests_count"] or 0),
                ok=int(row["success_count"] or 0),
                fail=int(row["fail_count"] or 0),
            )
        )
    if len(rows) > 80:
        lines.append(f"...и еще {len(rows) - 80}")
    await message.reply_text("\n".join(lines)[:3900])


async def delete_one_proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    tail = _command_tail(update)
    if not tail or not tail.split()[0].isdigit():
        await message.reply_text("Использование: /delete_one_proxy 123")
        return

    proxy_id = int(tail.split()[0])
    row = get_proxy_by_id(_settings(context), proxy_id)
    if not row:
        await message.reply_text(f"Прокси #{proxy_id} не найдена.")
        return

    await message.reply_text(
        "Удалить эту прокси из базы?\n\n"
        f"{_proxy_full_line(row)}\n\n"
        "Пароль показан полностью. Подтверди действие.",
        reply_markup=_confirm_keyboard(f"one:{proxy_id}"),
    )


async def delete_all_proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    settings = _settings(context)
    rows = list_proxies(settings, include_dead=True)
    if not rows:
        await message.reply_text("Прокси-пул уже пуст.")
        return

    counts = proxy_counts(settings)
    preview = [_proxy_full_line(row) for row in rows[:25]]
    if len(rows) > 25:
        preview.append(f"...и еще {len(rows) - 25}")
    await message.reply_text(
        "Удалить ВСЕ прокси из базы?\n\n"
        f"Всего: {counts['total']} | ACTIVE: {counts['active']} | DEAD: {counts['dead']}\n\n"
        + "\n".join(preview)
        + "\n\nПароли показаны полностью. Подтверди действие.",
        reply_markup=_confirm_keyboard("all"),
    )


async def proxy_delete_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    settings = _settings(context)
    user = update.effective_user
    if not is_admin(settings, user.id if user else None):
        await query.answer("Только админ.", show_alert=True)
        return

    data = query.data or ""
    payload = data.removeprefix(PROXY_DELETE_CONFIRM_PREFIX)
    parts = payload.split(":")
    if not parts:
        await query.answer("Некорректная команда.", show_alert=True)
        return

    action = parts[0]
    decision = parts[-1]
    if decision != "yes":
        await query.answer("Отменено.")
        await query.edit_message_text("Удаление прокси отменено.")
        return

    if action == "all":
        deleted = delete_all_proxies(settings, admin_id=user.id if user else None)
        await query.answer("Удалено.")
        await query.edit_message_text(f"Удалены все прокси из базы. Количество: {deleted}")
        return

    if action == "one" and len(parts) >= 3 and parts[1].isdigit():
        proxy_id = int(parts[1])
        deleted_row = delete_proxy_by_id(settings, proxy_id, admin_id=user.id if user else None)
        if not deleted_row:
            await query.answer("Уже не найдена.", show_alert=True)
            await query.edit_message_text(f"Прокси #{proxy_id} уже не найдена.")
            return
        await query.answer("Удалено.")
        await query.edit_message_text("Прокси удалена:\n\n" + _proxy_full_line(deleted_row))
        return

    await query.answer("Некорректная команда.", show_alert=True)


async def proxy_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    stats = proxy_stats(_settings(context))
    dead_rows = list_proxies(_settings(context), include_dead=True)
    dead_rows = [row for row in dead_rows if row.get("status") == "DEAD"][-8:]
    lines = [
        "Proxy stats",
        f"Активных: {stats['active']}",
        f"Мертвых: {stats['dead']}",
        f"Всего добавлялось: {stats['total']}",
        f"Успешных запросов: {stats['success']}",
        f"Ошибок: {stats['fail']}",
        f"Средняя жизнь: {stats['avg_requests']} запросов",
        f"Средняя жизнь: {stats['avg_days']} дней",
    ]
    if dead_rows:
        lines.append("")
        lines.append("Последние умершие:")
        for row in dead_rows:
            error = str(row.get("last_error") or "-")
            country = str(row.get("country_code") or "??").upper()
            lines.append(
                f"#{row['id']} {country} req={row['requests_count']} "
                f"{mask_proxy(str(row['proxy_url']))} | {error[:120]}"
            )
    await message.reply_text("\n".join(lines)[:3900])


async def proxy_hs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    message = update.message
    if not message:
        return

    settings = _settings(context)
    filled = backfill_proxy_countries(settings)
    rows = proxy_health_stats(settings)
    if not rows:
        await message.reply_text("Proxy health: proxy pool is empty. Add proxies with /add_proxy_list.")
        return

    total = sum(int(row["total"]) for row in rows)
    active = sum(int(row["active"]) for row in rows)
    dead = sum(int(row["dead"]) for row in rows)
    lines = [
        "Proxy health by country",
        f"Total: {total} | Active: {active} | Dead: {dead}",
    ]
    if filled:
        lines.append(f"Country auto-filled now: {filled}")
    lines.append("")

    for row in rows:
        dead_days = float(row["avg_dead_life_days"])
        active_days = float(row["avg_active_age_days"])
        dead_days_text = f"{dead_days}d" if dead_days else "-"
        active_days_text = f"{active_days}d" if active_days else "-"
        lines.append(str(row["label"]))
        lines.append(
            "active/dead/total: {active}/{dead}/{total} | avg active age: {active_days} | avg dead life: {dead_days}".format(
                active=row["active"],
                dead=row["dead"],
                total=row["total"],
                active_days=active_days_text,
                dead_days=dead_days_text,
            )
        )
        lines.append(
            "avg req/proxy: {avg_requests} | ok/fail: {success}/{fail}".format(
                avg_requests=row["avg_requests"],
                success=row["success"],
                fail=row["fail"],
            )
        )
        last_dead = row.get("last_dead")
        if isinstance(last_dead, dict):
            error = str(last_dead.get("last_error") or "-")
            lines.append(
                "last dead: #{id} req={requests} {proxy} | {error}".format(
                    id=last_dead.get("id"),
                    requests=last_dead.get("requests_count"),
                    proxy=mask_proxy(str(last_dead.get("proxy_url") or "")),
                    error=error[:100],
                )
            )
        lines.append("")

    await message.reply_text("\n".join(lines)[:3900])
