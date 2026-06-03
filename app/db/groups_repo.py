from datetime import datetime, timezone

from app.config import Settings
from app.db.database import db_connect


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chat_title(chat) -> str:
    return str(getattr(chat, "title", None) or getattr(chat, "full_name", None) or getattr(chat, "id", ""))


def _chat_username(chat) -> str | None:
    username = getattr(chat, "username", None)
    return str(username).strip() if username else None


def _chat_type(chat) -> str:
    return str(getattr(chat, "type", "") or "")


def upsert_bot_group(
    settings: Settings,
    chat,
    *,
    status: str = "active",
    added_by_user_id: int | None = None,
    increment_requests: bool = False,
) -> None:
    current = now_iso()
    chat_id = int(getattr(chat, "id"))
    title = _chat_title(chat)
    username = _chat_username(chat)
    chat_type = _chat_type(chat)
    request_increment = 1 if increment_requests else 0

    conn = db_connect(settings)

    conn.execute(
        """
        INSERT OR IGNORE INTO bot_groups (
            chat_id, title, username, chat_type, status, added_by_user_id,
            first_seen, last_seen, last_activity_at, requests_count, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            chat_id,
            title,
            username,
            chat_type,
            status,
            added_by_user_id,
            current,
            current,
            current if increment_requests else None,
            current,
        ),
    )

    conn.execute(
        """
        UPDATE bot_groups
        SET title = ?,
            username = ?,
            chat_type = ?,
            status = ?,
            added_by_user_id = COALESCE(?, added_by_user_id),
            last_seen = ?,
            last_activity_at = CASE WHEN ? = 1 THEN ? ELSE last_activity_at END,
            requests_count = requests_count + ?,
            updated_at = ?
        WHERE chat_id = ?
        """,
        (
            title,
            username,
            chat_type,
            status,
            added_by_user_id,
            current,
            1 if increment_requests else 0,
            current,
            request_increment,
            current,
            chat_id,
        ),
    )

    conn.commit()
    conn.close()


def record_group_activity(settings: Settings, chat) -> None:
    upsert_bot_group(
        settings,
        chat,
        status="active",
        increment_requests=True,
    )


def list_bot_groups(settings: Settings, *, limit: int = 50):
    conn = db_connect(settings)
    rows = conn.execute(
        """
        SELECT
            chat_id, title, username, chat_type, status, added_by_user_id,
            first_seen, last_seen, last_activity_at, requests_count, updated_at
        FROM bot_groups
        ORDER BY
            CASE WHEN status IN ('active', 'member', 'administrator') THEN 0 ELSE 1 END,
            COALESCE(last_activity_at, last_seen, updated_at) DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    conn.close()
    return rows


def count_bot_groups(settings: Settings) -> tuple[int, int]:
    conn = db_connect(settings)
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('active', 'member', 'administrator') THEN 1 ELSE 0 END) AS active
        FROM bot_groups
        """
    ).fetchone()
    conn.close()
    return int(row["total"] or 0), int(row["active"] or 0)
