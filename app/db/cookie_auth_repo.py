from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.config import Settings
from app.db.database import db_connect


COOKIE_PLATFORMS = ("youtube", "instagram", "tiktok", "pinterest")
COOKIE_SLOTS = (0, 1, 2, 3)


@dataclass(frozen=True)
class CookieRotationRecord:
    platform: str
    failed_slot: int
    next_slot: int
    lived_count: int
    reason: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_cookie_platform(platform: str | None) -> str | None:
    if not platform:
        return None

    platform = str(platform).lower().strip()

    if platform == "youtube_music":
        return "youtube"

    if platform in COOKIE_PLATFORMS:
        return platform

    return None


def setting_key_for_platform(platform: str) -> str:
    return f"{platform}_auth_slot"


def get_auth_slot(settings: Settings, platform: str | None) -> int:
    platform = normalize_cookie_platform(platform)

    if not platform:
        return 0

    conn = db_connect(settings)
    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key = ?",
        (setting_key_for_platform(platform),),
    ).fetchone()
    conn.close()

    if not row:
        return 0

    try:
        slot = int(row["value"])
    except Exception:
        return 0

    return slot if slot in COOKIE_SLOTS else 0


def set_auth_slot(settings: Settings, platform: str, slot: int) -> None:
    platform = normalize_cookie_platform(platform)

    if not platform or slot not in COOKIE_SLOTS:
        return

    current = now_iso()
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (setting_key_for_platform(platform), str(slot), current))
    conn.commit()
    conn.close()


def _finish_lifetime_sql(conn, platform: str, slot: int, current: str) -> int:
    row = conn.execute("""
        SELECT current_count
        FROM cookie_account_stats
        WHERE platform = ? AND slot = ?
    """, (platform, slot)).fetchone()

    lived_count = int(row["current_count"] or 0) if row else 0

    if lived_count > 0:
        conn.execute("""
            UPDATE cookie_account_stats
            SET lifetime_sum = lifetime_sum + ?,
                lifetime_count = lifetime_count + 1,
                current_count = 0,
                updated_at = ?
            WHERE platform = ? AND slot = ?
        """, (lived_count, current, platform, slot))
    else:
        conn.execute("""
            UPDATE cookie_account_stats
            SET current_count = 0,
                updated_at = ?
            WHERE platform = ? AND slot = ?
        """, (current, platform, slot))

    return lived_count


def rotate_auth_slot(
    settings: Settings,
    *,
    platform: str,
    failed_slot: int,
    reason: str | None = None,
) -> CookieRotationRecord:
    platform = normalize_cookie_platform(platform)

    if not platform:
        return CookieRotationRecord("unknown", failed_slot, failed_slot, 0, reason)

    failed_slot = failed_slot if failed_slot in COOKIE_SLOTS else 0
    next_slot = (failed_slot + 1) % 4
    current = now_iso()

    conn = db_connect(settings)
    lived_count = _finish_lifetime_sql(conn, platform, failed_slot, current)

    conn.execute("""
        UPDATE cookie_account_stats
        SET last_started_at = ?,
            updated_at = ?
        WHERE platform = ? AND slot = ?
    """, (current, current, platform, next_slot))

    conn.execute("""
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (setting_key_for_platform(platform), str(next_slot), current))

    conn.commit()
    conn.close()

    return CookieRotationRecord(
        platform=platform,
        failed_slot=failed_slot,
        next_slot=next_slot,
        lived_count=lived_count,
        reason=reason,
    )


def increment_cookie_success(settings: Settings, platform: str | None, slot: int | None, amount: int = 1) -> None:
    platform = normalize_cookie_platform(platform)

    if not platform:
        return

    if slot is None:
        slot = get_auth_slot(settings, platform)

    if slot not in COOKIE_SLOTS:
        slot = 0

    current = now_iso()
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO cookie_account_stats (
            platform, slot, current_count, total_count,
            lifetime_sum, lifetime_count,
            last_replaced_at, last_started_at, updated_at
        )
        VALUES (?, ?, ?, ?, 0, 0, NULL, ?, ?)
        ON CONFLICT(platform, slot) DO UPDATE SET
            current_count = current_count + excluded.current_count,
            total_count = total_count + excluded.total_count,
            updated_at = excluded.updated_at
    """, (platform, slot, amount, amount, current, current))
    conn.commit()
    conn.close()


def mark_cookie_replaced(settings: Settings, platform: str, slot: int) -> int:
    platform = normalize_cookie_platform(platform)

    if not platform or slot not in COOKIE_SLOTS:
        return 0

    current = now_iso()
    conn = db_connect(settings)
    lived_count = _finish_lifetime_sql(conn, platform, slot, current)

    conn.execute("""
        UPDATE cookie_account_stats
        SET last_replaced_at = ?,
            last_started_at = ?,
            updated_at = ?
        WHERE platform = ? AND slot = ?
    """, (current, current, current, platform, slot))

    conn.commit()
    conn.close()

    return lived_count


def get_cookie_stats(settings: Settings):
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
    return rows


def log_admin_action(
    settings: Settings,
    *,
    admin_id: int | None,
    action: str,
    target: str | None = None,
    details: str | None = None,
) -> None:
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO admin_actions (admin_id, action, target, details, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (admin_id, action, target, details, now_iso()))
    conn.commit()
    conn.close()


def to_local_display(value: str | None, offset_hours: int) -> str:
    if not value:
        return "-"

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = dt.astimezone(timezone(timedelta(hours=offset_hours)))
    return local_dt.strftime("%Y-%m-%d %H:%M")

