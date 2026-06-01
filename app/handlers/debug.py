import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.downloader.media_inspector import summarize_media
from app.downloader.metadata import fetch_metadata, format_duration
from app.downloader.routing import make_route_decision


logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")


def _extract_url(text: str) -> str | None:
    match = URL_RE.search(text or "")

    if not match:
        return None

    return match.group(0).strip(" <>[]()\"'")


def _safe_filename_part(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)
    return value[:80] or "meta"


def _short(value: Any, limit: int = 500) -> str:
    if value is None:
        return "None"

    text = str(value).replace("\n", "\\n")

    if len(text) <= limit:
        return text

    return text[:limit] + "..."


def _top_level_keys(info: dict[str, Any]) -> str:
    keys = sorted([str(k) for k in info.keys()])
    return ", ".join(keys[:80])


def _entries_preview(info: dict[str, Any], limit: int = 5) -> str:
    entries = info.get("entries") or []

    if not isinstance(entries, list) or not entries:
        return "no entries"

    lines = []

    for index, entry in enumerate(entries[:limit], 1):
        if not isinstance(entry, dict):
            lines.append(f"{index}. {type(entry).__name__}")
            continue

        lines.append(
            f"{index}. id={_short(entry.get('id'), 80)} | "
            f"title={_short(entry.get('title'), 120)} | "
            f"ext={entry.get('ext')} | "
            f"duration={entry.get('duration')} | "
            f"url={_short(entry.get('url'), 160)} | "
            f"thumbnail={_short(entry.get('thumbnail'), 160)}"
        )

    return "\n".join(lines)


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    logger.info(
        "PING command received | user_id=%s username=%s chat_id=%s",
        user.id if user else None,
        user.username if user else None,
        chat.id if chat else None,
    )

    if update.message:
        await update.message.reply_text("pong ✅\nBot is alive.")


async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    if not is_admin(settings, user.id if user else None):
        logger.warning(
            "DEBUG command denied | user_id=%s username=%s",
            user.id if user else None,
            user.username if user else None,
        )

        if update.message:
            await update.message.reply_text("Эта команда доступна только админу.")
        return

    me = await context.bot.get_me()
    webhook_info = await context.bot.get_webhook_info()

    text = (
        "Debug info:\n\n"
        f"Bot: @{me.username}\n"
        f"Bot ID: {me.id}\n"
        f"Webhook URL: {webhook_info.url or 'empty'}\n"
        f"Pending updates: {webhook_info.pending_update_count}\n"
        f"Last webhook error: {webhook_info.last_error_message or 'none'}\n"
        f"DB: {settings.db_path}\n"
        f"ENV: {settings.env_file}\n"
        f"LOG_LEVEL: {settings.log_level}\n"
        f"USE_LOCAL_BOT_API: {settings.use_local_bot_api}\n"
    )

    logger.info("DEBUG command completed | user_id=%s", user.id)

    if update.message:
        await update.message.reply_text(text)


async def debug_meta_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user

    if not is_admin(settings, user.id if user else None):
        if update.message:
            await update.message.reply_text("Эта команда доступна только админу.")
        return

    if not update.message:
        return

    url = _extract_url(update.message.text or "")

    if not url:
        await update.message.reply_text(
            "Пришли так:\n/debug_meta https://example.com/..."
        )
        return

    await update.message.reply_text("🔍 Читаю metadata...")

    started = time.time()

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(fetch_metadata, settings, url),
            timeout=60,
        )
    except Exception as e:
        logger.exception("debug_meta failed | url=%s", url)
        await update.message.reply_text(
            f"❌ Metadata failed:\n{type(e).__name__}: {_short(e, 1200)}"
        )
        return

    elapsed = time.time() - started

    summary = summarize_media(info)
    route = make_route_decision(url, info)

    logs_dir = settings.base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    extractor = str(info.get("extractor_key") or info.get("extractor") or "unknown")
    media_id = str(info.get("id") or "no_id")

    filename = (
        f"debug_meta_{int(time.time())}_"
        f"{_safe_filename_part(extractor)}_"
        f"{_safe_filename_part(media_id)}.json"
    )

    dump_path = logs_dir / filename

    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2, default=str)

    entries = info.get("entries") or []
    entries_count = len(entries) if isinstance(entries, list) else 0

    text = (
        "DEBUG META\n\n"
        f"Elapsed: {elapsed:.1f}s\n"
        f"Original URL: {_short(url, 400)}\n"
        f"Resolved URL: {_short(info.get('_resolved_url'), 400)}\n"
        f"Webpage URL: {_short(info.get('webpage_url'), 400)}\n\n"
        f"Extractor: {info.get('extractor_key') or info.get('extractor')}\n"
        f"ID: {info.get('id')}\n"
        f"Title: {_short(info.get('title'), 300)}\n"
        f"Duration: {format_duration(info.get('duration'))}\n"
        f"Ext: {info.get('ext')}\n"
        f"Entries: {entries_count}\n\n"
        "MEDIA SUMMARY\n"
        f"Photos: {summary.photo_count}\n"
        f"Videos: {summary.video_count}\n"
        f"Audio: {summary.audio_count}\n"
        f"Unknown: {summary.unknown_count}\n"
        f"Detected from: {summary.detected_from}\n\n"
        "ROUTE\n"
        f"Platform: {route.platform.value}\n"
        f"Content type: {route.content_type.value}\n"
        f"Action: {route.action.value}\n\n"
        "ENTRIES PREVIEW\n"
        f"{_entries_preview(info)}\n\n"
        f"JSON saved:\n{dump_path}"
    )

    if len(text) > 3900:
        text = text[:3900] + "\n\n...truncated"

    await update.message.reply_text(text)
