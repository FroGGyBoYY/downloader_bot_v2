from datetime import datetime, timedelta, timezone

from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import get_all_admin_ids
from app.db.cookie_auth_repo import COOKIE_PLATFORMS, COOKIE_SLOTS, get_auth_slot, to_local_display
from app.db.database import db_connect
from app.downloader.cookies import get_cookie_slot_path, is_cookie_slot_usable


PLATFORM_LABELS = {
    "youtube": "YouTube / YouTube Music",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "pinterest": "Pinterest",
}


def _cutoff(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _slot_state(settings: Settings, platform: str, slot: int) -> tuple[str, str]:
    if slot == 0:
        return "ok", "guest"

    path = get_cookie_slot_path(settings, platform, slot, require_existing=False)

    if not path:
        return "missing", "-"

    if not path.exists():
        return "missing", path.name

    if path.stat().st_size <= 0:
        return "empty", path.name

    return "ok", path.name


def build_cookie_health_report(settings: Settings, *, only_problems: bool = False) -> tuple[str, bool]:
    lines = ["Cookie health"]
    has_problem = False

    for platform in COOKIE_PLATFORMS:
        active_slot = get_auth_slot(settings, platform)
        lines.append("")
        lines.append(f"{PLATFORM_LABELS.get(platform, platform)}: active slot {active_slot}")

        for slot in COOKIE_SLOTS:
            state, filename = _slot_state(settings, platform, slot)
            usable = is_cookie_slot_usable(settings, platform, slot)
            is_problem = slot == active_slot and not usable

            if is_problem:
                has_problem = True

            if only_problems and not is_problem:
                continue

            marker = "!" if is_problem else "-"
            lines.append(f"{marker} slot {slot}: {state} | {filename}")

    if only_problems and not has_problem:
        return "Cookie health: ok", False

    return "\n".join(lines), has_problem


def build_platform_health_report(settings: Settings, *, hours: int = 24) -> str:
    cutoff = _cutoff(hours)
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT
            COALESCE(platform, '-') AS platform,
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            MAX(CASE WHEN status = 'failed' THEN error_text ELSE NULL END) AS last_error
        FROM download_requests
        WHERE created_at >= ?
        GROUP BY COALESCE(platform, '-')
        ORDER BY failed DESC, total DESC
    """, (cutoff,)).fetchall()
    conn.close()

    lines = [f"Platform health, last {hours}h"]

    if not rows:
        lines.append("No downloads yet.")
    else:
        for row in rows:
            total = int(row["total"] or 0)
            sent = int(row["sent"] or 0)
            failed = int(row["failed"] or 0)
            fail_rate = (failed / total * 100) if total else 0
            state = "OK" if fail_rate < 20 else "WARN"
            lines.append(
                f"{state} {row['platform']}: total {total}, sent {sent}, failed {failed}, fail {fail_rate:.0f}%"
            )

            if row["last_error"]:
                lines.append(f"  last error: {str(row['last_error'])[:180]}")

    lines.append("")
    lines.append("Active auth slots:")

    for platform in COOKIE_PLATFORMS:
        slot = get_auth_slot(settings, platform)
        state, filename = _slot_state(settings, platform, slot)
        lines.append(f"{PLATFORM_LABELS.get(platform, platform)}: slot {slot} | {state} | {filename}")

    return "\n".join(lines)


async def send_cookie_health_if_needed(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    text, has_problem = build_cookie_health_report(settings, only_problems=True)

    if not has_problem:
        return

    for admin_id in sorted(get_all_admin_ids(settings)):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text[:3900])
        except Exception:
            pass


def build_cookie_stats_table(settings: Settings) -> str:
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM cookie_account_stats
        ORDER BY slot ASC,
            CASE platform
                WHEN 'youtube' THEN 1
                WHEN 'instagram' THEN 2
                WHEN 'tiktok' THEN 3
                WHEN 'pinterest' THEN 4
                ELSE 9
            END ASC
    """).fetchall()
    conn.close()

    lines = ["Cookie stats"]

    for row in rows:
        lifetime_count = int(row["lifetime_count"] or 0)
        avg = "-"

        if lifetime_count > 0:
            avg = str(round(int(row["lifetime_sum"] or 0) / lifetime_count))

        slot_label = "guest" if int(row["slot"]) == 0 else f"cookies_{row['slot']}"
        last = row["last_replaced_at"] or row["last_started_at"]
        lines.append(
            f"{slot_label} | {row['platform']} | current {row['current_count']} | "
            f"avg {avg} | last {to_local_display(last, settings.local_tz_hours)}"
        )

    return "\n".join(lines)
