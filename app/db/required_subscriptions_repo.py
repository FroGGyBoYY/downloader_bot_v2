from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso
from app.texts.keys import TextKey
from app.texts.renderer import render_text


ACTIVE = "ACTIVE"
PAUSED = "PAUSED"
DELETED = "DELETED"

RESOURCE_TYPES = {"channel", "bot", "mini_app", "link"}
CHECKABLE_TYPES = {"channel"}
CLICK_SATISFIED_TYPES = {"bot", "mini_app", "link"}
TEXT_SETTING_KEY = "required_subscriptions_text"

DEFAULT_REQUIRED_TEXT = (
    "Чтобы пользоваться ботом, подпишись на обязательные ресурсы ниже.\n\n"
    "После подписки нажми кнопку проверки."
)


def create_required_resource(
    settings: Settings,
    *,
    resource_type: str,
    target_chat: str | None,
    checker_bot_key: str = "main",
    button_text: str,
    button_url: str,
    button_style: str | None,
    created_by: int | None,
) -> int:
    resource_type = resource_type.lower().strip()

    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"Unsupported resource_type: {resource_type}")

    current = now_iso()
    conn = db_connect(settings)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO required_resources (
            status, resource_type, target_chat, checker_bot_key,
            button_text, button_url, button_style,
            created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ACTIVE,
        resource_type,
        target_chat,
        checker_bot_key or "main",
        button_text,
        button_url,
        button_style,
        created_by,
        current,
        current,
    ))

    resource_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return resource_id


def get_required_resource(settings: Settings, resource_id: int):
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT * FROM required_resources WHERE id = ?",
        (resource_id,),
    ).fetchone()
    conn.close()
    return row


def list_required_resources(settings: Settings, *, active_only: bool = False, limit: int = 50):
    conn = db_connect(settings)

    if active_only:
        rows = conn.execute("""
            SELECT *
            FROM required_resources
            WHERE status = ?
            ORDER BY id ASC
        """, (ACTIVE,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT *
            FROM required_resources
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    conn.close()
    return rows


def list_current_required_resources(settings: Settings, *, limit: int = 50):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM required_resources
        WHERE status IN (?, ?)
        ORDER BY id DESC
        LIMIT ?
    """, (ACTIVE, PAUSED, limit)).fetchall()
    conn.close()
    return rows


def set_required_resource_status(settings: Settings, resource_id: int, status: str) -> bool:
    status = status.upper().strip()

    if status not in {ACTIVE, PAUSED, DELETED}:
        return False

    current = now_iso()
    conn = db_connect(settings)
    cur = conn.execute("""
        UPDATE required_resources
        SET status = ?,
            updated_at = ?
        WHERE id = ?
    """, (status, current, resource_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_required_resource_button(
    settings: Settings,
    *,
    resource_id: int,
    button_text: str,
    button_url: str,
    button_style: str | None,
) -> bool:
    current = now_iso()
    conn = db_connect(settings)
    cur = conn.execute("""
        UPDATE required_resources
        SET button_text = ?,
            button_url = ?,
            button_style = ?,
            updated_at = ?
        WHERE id = ?
    """, (button_text, button_url, button_style, current, resource_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def update_required_resource_checker(
    settings: Settings,
    *,
    resource_id: int,
    checker_bot_key: str,
) -> bool:
    current = now_iso()
    conn = db_connect(settings)
    cur = conn.execute("""
        UPDATE required_resources
        SET checker_bot_key = ?,
            updated_at = ?
        WHERE id = ?
    """, (checker_bot_key or "main", current, resource_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def set_required_subscriptions_text(settings: Settings, text: str) -> None:
    current = now_iso()
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (TEXT_SETTING_KEY, text, current))
    conn.commit()
    conn.close()


def get_required_subscriptions_text(settings: Settings, language_code: str | None = None) -> str:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key = ?",
        (TEXT_SETTING_KEY,),
    ).fetchone()
    conn.close()

    if not row or not str(row["value"] or "").strip():
        text, _ = render_text(TextKey.REQUIRED_SUBSCRIPTIONS_TEXT, language_code=language_code)
        return text

    return str(row["value"]).strip()


def is_user_resource_satisfied(settings: Settings, *, resource_id: int, user_id: int) -> bool:
    conn = db_connect(settings)
    row = conn.execute("""
        SELECT 1
        FROM required_resource_user_state
        WHERE resource_id = ? AND user_id = ?
    """, (resource_id, user_id)).fetchone()
    conn.close()
    return bool(row)


def mark_user_resource_satisfied(
    settings: Settings,
    *,
    resource_id: int,
    user_id: int,
    satisfied_by: str,
) -> None:
    current = now_iso()
    conn = db_connect(settings)
    conn.execute("""
        INSERT INTO required_resource_user_state (
            resource_id, user_id, satisfied_at, last_checked_at, satisfied_by
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(resource_id, user_id) DO UPDATE SET
            last_checked_at = excluded.last_checked_at,
            satisfied_by = excluded.satisfied_by
    """, (resource_id, user_id, current, current, satisfied_by))
    conn.commit()
    conn.close()


def record_required_event(
    settings: Settings,
    *,
    resource_id: int,
    event_type: str,
    user_id: int | None,
    chat_id: int | None,
    error_text: str | None = None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO required_resource_events (
            resource_id, event_type, user_id, chat_id, error_text, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        resource_id,
        event_type,
        user_id,
        chat_id,
        (error_text or "")[:700],
        current,
    ))

    counter_by_event = {
        "impression": "impressions_count",
        "click": "clicks_count",
        "pass": "passes_count",
        "fail": "fails_count",
        "check_error": "check_errors_count",
    }
    counter = counter_by_event.get(event_type)

    if counter:
        conn.execute(f"""
            UPDATE required_resources
            SET {counter} = {counter} + 1,
                updated_at = ?
            WHERE id = ?
        """, (current, resource_id))

    conn.commit()
    conn.close()


def get_required_unique_event_counts(settings: Settings, resource_id: int) -> dict[str, int]:
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT event_type, COUNT(DISTINCT user_id) AS unique_users
        FROM required_resource_events
        WHERE resource_id = ?
            AND user_id IS NOT NULL
        GROUP BY event_type
    """, (resource_id,)).fetchall()
    conn.close()

    return {
        str(row["event_type"]): int(row["unique_users"] or 0)
        for row in rows
    }
