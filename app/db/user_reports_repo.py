from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def create_user_report(
    settings: Settings,
    *,
    user_id: int,
    username: str | None,
    full_name: str,
    chat_id: int | None,
    message_id: int | None,
    report_text: str,
) -> int:
    current = now_iso()
    conn = db_connect(settings)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_reports (
            user_id, username, full_name, chat_id, message_id,
            report_text, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
    """, (
        user_id,
        username,
        full_name,
        chat_id,
        message_id,
        report_text,
        current,
        current,
    ))
    report_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return report_id


def list_recent_user_reports(settings: Settings, limit: int = 20):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM user_reports
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows


def count_open_user_reports(settings: Settings) -> int:
    conn = db_connect(settings)
    row = conn.execute("""
        SELECT COUNT(*) AS c
        FROM user_reports
        WHERE status = 'open'
    """).fetchone()
    conn.close()
    return int(row["c"] or 0)
