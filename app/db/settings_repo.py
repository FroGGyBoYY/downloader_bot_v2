from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def get_setting(settings: Settings, key: str, default: str | None = None) -> str | None:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()

    if not row:
        return default

    return row["value"]


def set_setting(settings: Settings, key: str, value: str | None) -> None:
    current = now_iso()
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (key, value, current))
    conn.commit()
    conn.close()


def get_bool_setting(settings: Settings, key: str, default: bool = False) -> bool:
    value = get_setting(settings, key, "1" if default else "0")
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
