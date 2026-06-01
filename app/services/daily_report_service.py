from datetime import datetime, timedelta, timezone

from telegram.ext import ContextTypes

from app.config import Settings
from app.db.admin_repo import get_all_admin_ids
from app.db.database import db_connect
from app.db.user_reports_repo import count_open_user_reports


def _cutoff(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _count(conn, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row["c"] or 0) if row else 0


def build_daily_admin_report(settings: Settings) -> str:
    cutoff = _cutoff(24)
    conn = db_connect(settings)

    total_users = _count(conn, "SELECT COUNT(*) AS c FROM users")
    new_users = _count(conn, "SELECT COUNT(*) AS c FROM users WHERE first_seen >= ?", (cutoff,))
    active_users = _count(conn, "SELECT COUNT(*) AS c FROM users WHERE last_seen >= ?", (cutoff,))
    sent = _count(conn, "SELECT COUNT(*) AS c FROM download_requests WHERE status = 'sent' AND created_at >= ?", (cutoff,))
    failed = _count(conn, "SELECT COUNT(*) AS c FROM download_requests WHERE status = 'failed' AND created_at >= ?", (cutoff,))
    cache_hits = _count(conn, "SELECT COUNT(*) AS c FROM download_requests WHERE cache_status = 'hit' AND created_at >= ?", (cutoff,))
    bot_errors = _count(conn, "SELECT COUNT(*) AS c FROM bot_errors WHERE created_at >= ?", (cutoff,))
    ad_views = _count(conn, "SELECT COUNT(*) AS c FROM ad_events WHERE event_type = 'impression' AND created_at >= ?", (cutoff,))
    ad_clicks = _count(conn, "SELECT COUNT(*) AS c FROM ad_events WHERE event_type = 'click' AND created_at >= ?", (cutoff,))
    req_views = _count(conn, "SELECT COUNT(*) AS c FROM required_resource_events WHERE event_type = 'impression' AND created_at >= ?", (cutoff,))
    req_pass = _count(conn, "SELECT COUNT(*) AS c FROM required_resource_events WHERE event_type = 'pass' AND created_at >= ?", (cutoff,))

    platforms = conn.execute("""
        SELECT COALESCE(platform, '-') AS platform, COUNT(*) AS c
        FROM download_requests
        WHERE status = 'sent' AND created_at >= ?
        GROUP BY COALESCE(platform, '-')
        ORDER BY c DESC
    """, (cutoff,)).fetchall()

    top = conn.execute("""
        SELECT COALESCE(source_key, original_url) AS item_key,
               MAX(title) AS title,
               MAX(platform) AS platform,
               COUNT(*) AS c
        FROM download_requests
        WHERE status = 'sent' AND created_at >= ?
        GROUP BY COALESCE(source_key, original_url)
        ORDER BY c DESC
        LIMIT 5
    """, (cutoff,)).fetchall()

    conn.close()

    lines = [
        "Daily admin report",
        "Period: last 24h",
        "",
        f"Users total: {total_users}",
        f"New users: {new_users}",
        f"Active users: {active_users}",
        "",
        f"Downloads sent: {sent}",
        f"Failed downloads: {failed}",
        f"Cache hits: {cache_hits}",
        f"Unhandled errors: {bot_errors}",
        f"Open user reports: {count_open_user_reports(settings)}",
        "",
        f"Ad views/clicks: {ad_views}/{ad_clicks}",
        f"Required subscriptions views/pass: {req_views}/{req_pass}",
        "",
        "By platform:",
    ]

    if platforms:
        lines.extend([f"- {row['platform']}: {row['c']}" for row in platforms])
    else:
        lines.append("- no data")

    lines.append("")
    lines.append("Top downloads:")

    if top:
        for index, row in enumerate(top, 1):
            lines.append(f"{index}. {row['title'] or row['item_key']} | {row['platform'] or '-'} | {row['c']}")
    else:
        lines.append("- no data")

    return "\n".join(lines)


async def send_daily_admin_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    text = build_daily_admin_report(settings)

    for admin_id in sorted(get_all_admin_ids(settings)):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text[:3900])
        except Exception:
            pass
