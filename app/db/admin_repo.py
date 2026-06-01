from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def base_admin_ids(settings: Settings) -> set[int]:
    return set(settings.admin_ids or set())


def is_base_admin(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id and int(user_id) in base_admin_ids(settings))


def list_dynamic_admins(settings: Settings):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM admin_users
        ORDER BY created_at ASC
    """).fetchall()
    conn.close()
    return rows


def get_dynamic_admin_ids(settings: Settings) -> set[int]:
    return {
        int(row["user_id"])
        for row in list_dynamic_admins(settings)
    }


def get_all_admin_ids(settings: Settings) -> set[int]:
    return base_admin_ids(settings) | get_dynamic_admin_ids(settings)


def is_admin(settings: Settings, user_id: int | None) -> bool:
    return bool(user_id and int(user_id) in get_all_admin_ids(settings))


def add_admin(
    settings: Settings,
    *,
    user_id: int,
    username: str | None = None,
    full_name: str | None = None,
    note: str | None = None,
    added_by: int | None = None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO admin_users (
            user_id, username, full_name, note, added_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, admin_users.username),
            full_name = COALESCE(excluded.full_name, admin_users.full_name),
            note = COALESCE(excluded.note, admin_users.note),
            updated_at = excluded.updated_at
    """, (
        user_id,
        username,
        full_name,
        note,
        added_by,
        current,
        current,
    ))

    conn.commit()
    conn.close()


def remove_dynamic_admin(settings: Settings, *, user_id: int) -> bool:
    conn = db_connect(settings)
    cur = conn.execute(
        "DELETE FROM admin_users WHERE user_id = ?",
        (user_id,),
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
