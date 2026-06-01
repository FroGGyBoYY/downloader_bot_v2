from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def record_bot_error(
    settings: Settings,
    *,
    error_type: str | None,
    error_text: str | None,
    traceback_text: str | None,
    update_type: str | None,
    user_id: int | None,
    chat_id: int | None,
    update_preview: str | None,
) -> None:
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO bot_errors (
            error_type, error_text, traceback_text, update_type,
            user_id, chat_id, update_preview, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        (error_type or "")[:200],
        (error_text or "")[:1000],
        (traceback_text or "")[:5000],
        (update_type or "")[:100],
        user_id,
        chat_id,
        (update_preview or "")[:3000],
        now_iso(),
    ))
    conn.commit()
    conn.close()
