import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import is_admin
from app.db.cookie_auth_repo import (
    get_auth_slot,
    get_cookie_stats,
    log_admin_action,
    mark_cookie_replaced,
    to_local_display,
)
from app.downloader.cookies import get_cookie_slot_path


logger = logging.getLogger(__name__)


COMMANDS = {
    "ccy": ("youtube", "YouTube", ("youtube.com", "google.com")),
    "cct": ("tiktok", "TikTok", ("tiktok.com",)),
    "cci": ("instagram", "Instagram", ("instagram.com",)),
    "ccp": ("pinterest", "Pinterest", ("pinterest.com", "pin.it")),
}


PLATFORM_RU = {
    "youtube": "ютуб",
    "instagram": "инст",
    "tiktok": "тикток",
    "pinterest": "пинтерест",
}


SLOT_RU = {
    0: "гость",
    1: "куки_1",
    2: "куки_2",
    3: "куки_3",
}


def _is_admin(settings: Settings, user_id: int | None) -> bool:
    return is_admin(settings, user_id)


def _command_name(message: Message) -> str:
    text = message.text or message.caption or ""
    first = text.split(maxsplit=1)[0] if text.strip() else ""
    return first.lstrip("/").split("@", 1)[0].lower()


def _parse_cookie_command(command: str) -> tuple[str, int] | None:
    legacy = re.fullmatch(r"change_cookies_([123])", command)

    if legacy:
        return "youtube", int(legacy.group(1))

    match = re.fullmatch(r"(ccy|cct|cci|ccp)_([123])", command)

    if not match:
        return None

    platform, _, allowed_domains = COMMANDS[match.group(1)]
    return platform, int(match.group(2))


def _platform_config(platform: str) -> tuple[str, tuple[str, ...]]:
    for _, (candidate, label, domains) in COMMANDS.items():
        if candidate == platform:
            return label, domains

    return platform, ()


def _command_tail(message: Message) -> str:
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _looks_like_netscape_cookies(text: str) -> bool:
    if "Netscape HTTP Cookie File" in text:
        return True

    for line in text.splitlines():
        line = line.strip()

        if not line or (line.startswith("#") and not line.lower().startswith("#httponly_")):
            continue

        if len(line.split("\t")) >= 7:
            return True

    return False


def _cookie_domains(text: str) -> set[str]:
    domains: set[str] = set()

    for line in text.splitlines():
        line = line.strip()

        if not line or (line.startswith("#") and not line.lower().startswith("#httponly_")):
            continue

        parts = line.split("\t")

        if len(parts) < 7:
            continue

        domain = parts[0].strip().lower()

        if domain.startswith("#httponly_"):
            domain = domain.replace("#httponly_", "", 1)

        domain = domain.lstrip(".")

        if domain:
            domains.add(domain)

    return domains


def _validate_cookie_text(text: str, allowed_domains: tuple[str, ...]) -> str | None:
    if not text.strip():
        return "Файл cookies пустой."

    if not _looks_like_netscape_cookies(text):
        return "Файл не похож на Netscape cookies.txt."

    domains = _cookie_domains(text)

    if not domains:
        return "Не нашел домены cookies в файле."

    for domain in domains:
        for allowed in allowed_domains:
            if domain == allowed or domain.endswith("." + allowed):
                return None

    return "Домены cookies не подходят для выбранной платформы."


async def _download_document_via_public_api(
    *,
    settings: Settings,
    file_id: str,
    destination: Path,
) -> None:
    timeout = httpx.Timeout(connect=30, read=120, write=120, pool=30)

    async with httpx.AsyncClient(timeout=timeout) as client:
        get_file = await client.get(
            f"https://api.telegram.org/bot{settings.bot_token}/getFile",
            params={"file_id": file_id},
        )
        get_file.raise_for_status()
        payload = get_file.json()

        if not payload.get("ok"):
            raise RuntimeError("Telegram public getFile failed")

        file_path = payload["result"]["file_path"]
        file_response = await client.get(
            f"https://api.telegram.org/file/bot{settings.bot_token}/{file_path}"
        )
        file_response.raise_for_status()

    destination.write_bytes(file_response.content)


async def _read_cookie_payload(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> str | None:
    message = update.message

    if not message:
        return None

    tail = _command_tail(message)

    if tail.strip():
        return tail

    reply = message.reply_to_message

    if not reply:
        await message.reply_text("Пришли команду reply на cookies.txt или на текст с cookies.")
        return None

    if reply.document:
        temp_root = settings.base_dir / "media" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=temp_root) as tmpdir:
            tmp_path = Path(tmpdir) / "cookies.txt"

            try:
                tg_file = await context.bot.get_file(reply.document.file_id)
                await tg_file.download_to_drive(custom_path=tmp_path)
            except (TelegramError, RuntimeError):
                if not settings.use_local_bot_api:
                    raise

                logger.warning("Local Bot API document download failed, trying public Telegram API")
                await _download_document_via_public_api(
                    settings=settings,
                    file_id=reply.document.file_id,
                    destination=tmp_path,
                )

            return tmp_path.read_text(encoding="utf-8", errors="replace")

    text = reply.text or reply.caption

    if text:
        return text

    await message.reply_text("В reply должен быть document cookies.txt или текст cookies.")
    return None


def _replace_cookie_file(target_path: Path, payload: str) -> Path | None:
    target_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None

    if target_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.bak.{timestamp}")
        shutil.copy2(target_path, backup_path)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        delete=False,
        dir=target_path.parent,
        prefix=f".{target_path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)

    tmp_path.replace(target_path)
    return backup_path


async def cookie_replace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    parsed = _parse_cookie_command(_command_name(message))

    if not parsed:
        await message.reply_text("Не понял команду cookies.")
        return

    platform, slot = parsed
    platform_label, allowed_domains = _platform_config(platform)

    payload = await _read_cookie_payload(update, context, settings)

    if payload is None:
        return

    validation_error = _validate_cookie_text(payload, allowed_domains)

    if validation_error:
        await message.reply_text(f"Не заменил cookies: {validation_error}")
        return

    target_path = get_cookie_slot_path(settings, platform, slot, require_existing=False)

    if not target_path:
        await message.reply_text("Не смог определить путь cookies-файла.")
        return

    backup_path = _replace_cookie_file(target_path, payload)
    lived_count = mark_cookie_replaced(settings, platform, slot)
    log_admin_action(
        settings,
        admin_id=user.id if user else None,
        action="replace_cookies",
        target=f"{platform}:{slot}",
        details=f"path={target_path.name} backup={backup_path.name if backup_path else '-'} lived={lived_count}",
    )

    await message.reply_text(
        "\n".join([
            f"{platform_label} cookies_{slot} заменены.",
            f"Файл: {target_path.name}",
            f"Backup: {backup_path.name if backup_path else '-'}",
            f"Предыдущая жизнь: {lived_count} запросов",
        ])
    )


async def cookie_check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    active_slots = {
        platform: get_auth_slot(settings, platform)
        for platform in ("youtube", "instagram", "tiktok", "pinterest")
    }

    lines = ["Cookie check", ""]

    for row in get_cookie_stats(settings):
        platform = row["platform"]
        slot = int(row["slot"])
        lifetime_count = int(row["lifetime_count"] or 0)
        lifetime_sum = int(row["lifetime_sum"] or 0)
        avg = "-" if lifetime_count <= 0 else str(round(lifetime_sum / lifetime_count, 1))
        date_value = row["last_replaced_at"] or row["last_started_at"]
        active = " *" if active_slots.get(platform) == slot else ""

        lines.append(
            f"{SLOT_RU.get(slot, slot)} | {PLATFORM_RU.get(platform, platform)}{active} | "
            f"сейчас: {row['current_count']} | средняя: {avg} | "
            f"{to_local_display(date_value, settings.local_tz_hours)}"
        )

    await message.reply_text("\n".join(lines)[:3900])


async def admin_cookies_help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    message = update.message

    if not message:
        return

    if not _is_admin(settings, user.id if user else None):
        await message.reply_text("Эта команда доступна только админу.")
        return

    await message.reply_text(
        "\n".join([
            "Admin commands",
            "",
            "/cookie_check",
            "/ccy_1 /ccy_2 /ccy_3 - YouTube cookies",
            "/cct_1 /cct_2 /cct_3 - TikTok cookies",
            "/cci_1 /cci_2 /cci_3 - Instagram cookies",
            "/ccp_1 /ccp_2 /ccp_3 - Pinterest cookies",
            "/admin_receive_video_on - import old YouTube video file_id cache",
            "/admin_receive_video_off - stop old video import mode",
            "",
            "Ads:",
            "/ad_add - reply to ad message; optional: Button text | https://url",
            "add - same as /ad_add, reply text shortcut",
            "/ad_list",
            "/ad_stats 1",
            "/ad_on 1 /ad_off 1",
            "/friend_add 123 /friend_del 123 /friend_list",
            "",
            "Required subscriptions:",
            "/req_add channel @channel Button | https://t.me/channel | checker=helper_1",
            "/req_add bot @SomeBot Button | https://t.me/SomeBot",
            "/req_add mini_app Button | https://t.me/bot/app",
            "/req_list",
            "/req_stats 1",
            "/req_on 1 /req_off 1",
            "/req_edit 1 Button | https://url",
            "/req_checker 1 helper_1",
            "/req_text text shown above required buttons",
            "",
            "Команды замены нужно отправлять reply на document cookies.txt или на текст cookies.",
        ])
    )
