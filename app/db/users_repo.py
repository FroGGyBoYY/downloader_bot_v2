from datetime import datetime, timezone
from typing import Optional

from telegram import User

from app.config import Settings
from app.db.database import db_connect
from app.texts.languages import normalize_language_code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_full_name(user: User | None) -> str:
    if not user:
        return ""

    parts = []

    if user.first_name:
        parts.append(user.first_name)

    if user.last_name:
        parts.append(user.last_name)

    return " ".join(parts).strip()


def upsert_user(settings: Settings, user: User | None) -> None:
    if not user:
        return

    current = now_iso()
    full_name = get_full_name(user)

    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO users (
            user_id, username, full_name, first_seen, last_seen
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name,
            last_seen = excluded.last_seen
    """, (
        user.id,
        user.username,
        full_name,
        current,
        current,
    ))

    conn.commit()
    conn.close()


def get_user_language(settings: Settings, user_id: int) -> Optional[str]:
    conn = db_connect(settings)

    row = conn.execute(
        "SELECT language_code FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return normalize_language_code(row["language_code"])


def set_user_language(settings: Settings, user: User | None, language_code: str) -> bool:
    if not user:
        return False

    normalized = normalize_language_code(language_code)

    if not normalized:
        return False

    upsert_user(settings, user)

    conn = db_connect(settings)
    current = now_iso()

    conn.execute("""
        UPDATE users
        SET language_code = ?,
            last_seen = ?
        WHERE user_id = ?
    """, (
        normalized,
        current,
        user.id,
    ))

    conn.execute("""
        INSERT INTO user_events (
            user_id, event_type, event_value, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user.id,
        "language_changed",
        normalized,
        current,
    ))

    conn.commit()
    conn.close()

    return True

def increment_user_request(settings: Settings, user_id: int) -> None:
    conn = db_connect(settings)
    conn.execute("""
        UPDATE users
        SET requests_count = requests_count + 1,
            last_seen = ?
        WHERE user_id = ?
    """, (now_iso(), user_id))
    conn.commit()
    conn.close()


def increment_user_download(settings: Settings, user_id: int) -> None:
    conn = db_connect(settings)
    conn.execute("""
        UPDATE users
        SET downloads_count = downloads_count + 1,
            last_seen = ?
        WHERE user_id = ?
    """, (now_iso(), user_id))
    conn.commit()
    conn.close()


def increment_user_cache_hit(settings: Settings, user_id: int) -> None:
    conn = db_connect(settings)
    conn.execute("""
        UPDATE users
        SET cache_hits_count = cache_hits_count + 1,
            last_seen = ?
        WHERE user_id = ?
    """, (now_iso(), user_id))
    conn.commit()
    conn.close()


def is_user_friend(settings: Settings, user_id: int) -> bool:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT is_friend FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return bool(row and row["is_friend"])


def is_user_subscribed(settings: Settings, user_id: int | None) -> bool:
    if not user_id:
        return False

    user_id = int(user_id)

    if user_id in set(settings.admin_ids or set()):
        return True

    conn = db_connect(settings)

    admin_row = conn.execute(
        "SELECT 1 FROM admin_users WHERE user_id = ? LIMIT 1",
        (user_id,),
    ).fetchone()

    if admin_row:
        conn.close()
        return True

    row = conn.execute(
        """
        SELECT is_friend, is_premium, subscription_status, subscription_until
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if not row:
        return False

    if row["is_friend"] or row["is_premium"]:
        return True

    status = str(row["subscription_status"] or "").strip().lower()
    if status not in {"active", "premium", "paid", "subscribed"}:
        return False

    until = str(row["subscription_until"] or "").strip()
    if not until:
        return True

    return until > now_iso()


def set_user_friend(
    settings: Settings,
    *,
    user_id: int,
    is_friend: bool,
    username: str | None = None,
    full_name: str | None = None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO users (
            user_id, username, full_name, first_seen, last_seen, is_friend
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, users.username),
            full_name = COALESCE(excluded.full_name, users.full_name),
            is_friend = excluded.is_friend,
            last_seen = excluded.last_seen
    """, (
        user_id,
        username,
        full_name or "",
        current,
        current,
        1 if is_friend else 0,
    ))

    conn.execute("""
        INSERT INTO user_events (
            user_id, event_type, event_value, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        "friend_status_changed",
        "1" if is_friend else "0",
        current,
    ))

    conn.commit()
    conn.close()


def list_friend_users(settings: Settings):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT user_id, username, full_name, last_seen
        FROM users
        WHERE is_friend = 1
        ORDER BY last_seen DESC
    """).fetchall()
    conn.close()
    return rows


def list_message_target_users(
    settings: Settings,
    *,
    include_friends: bool = True,
):
    conn = db_connect(settings)
    params: list = []
    where = ["is_banned = 0"]

    if not include_friends:
        where.append("is_friend = 0")

    rows = conn.execute(f"""
        SELECT user_id, username, full_name, is_friend, last_seen
        FROM users
        WHERE {" AND ".join(where)}
        ORDER BY last_seen DESC
    """, params).fetchall()
    conn.close()
    return rows


def is_user_banned(settings: Settings, user_id: int) -> bool:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT is_banned FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return bool(row and row["is_banned"])


def set_user_banned(
    settings: Settings,
    *,
    user_id: int,
    is_banned: bool,
    username: str | None = None,
    full_name: str | None = None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO users (
            user_id, username, full_name, first_seen, last_seen, is_banned
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, users.username),
            full_name = COALESCE(excluded.full_name, users.full_name),
            is_banned = excluded.is_banned,
            last_seen = excluded.last_seen
    """, (
        user_id,
        username,
        full_name or "",
        current,
        current,
        1 if is_banned else 0,
    ))

    conn.execute("""
        INSERT INTO user_events (
            user_id, event_type, event_value, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        "ban_status_changed",
        "1" if is_banned else "0",
        current,
    ))

    conn.commit()
    conn.close()


def list_banned_users(settings: Settings):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT user_id, username, full_name, last_seen
        FROM users
        WHERE is_banned = 1
        ORDER BY last_seen DESC
    """).fetchall()
    conn.close()
    return rows
