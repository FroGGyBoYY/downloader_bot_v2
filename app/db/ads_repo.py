from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


ACTIVE = "ACTIVE"
PAUSED = "PAUSED"
DELETED = "DELETED"
AFTER_DOWNLOAD_AD = "after_download"
SCHEDULED_AD = "scheduled_8h"


def normalize_campaign_type(value: str | None) -> str:
    value = str(value or "").strip().lower()

    if value in {SCHEDULED_AD, "scheduled", "ad8", "periodic"}:
        return SCHEDULED_AD

    return AFTER_DOWNLOAD_AD


def create_ad_campaign(
    settings: Settings,
    *,
    campaign_type: str = AFTER_DOWNLOAD_AD,
    source_chat_id: int,
    source_message_id: int,
    source_type: str | None,
    button_text: str | None,
    button_url: str | None,
    button_style: str | None,
    buttons: list[dict] | None = None,
    created_by: int | None,
) -> int:
    current = now_iso()
    conn = db_connect(settings)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO ad_campaigns (
            status, campaign_type, source_chat_id, source_message_id, source_type,
            button_text, button_url, button_style,
            created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ACTIVE,
        normalize_campaign_type(campaign_type),
        source_chat_id,
        source_message_id,
        source_type,
        button_text,
        button_url,
        button_style,
        created_by,
        current,
        current,
    ))

    ad_id = int(cur.lastrowid)

    button_rows = list(buttons or [])

    if not button_rows and button_text and button_url:
        button_rows = [{
            "button_text": button_text,
            "button_url": button_url,
            "button_style": button_style,
        }]

    for index, button in enumerate(button_rows):
        cur.execute("""
            INSERT INTO ad_buttons (
                ad_id, button_index, button_text, button_url, button_style, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ad_id,
            index,
            str(button.get("button_text") or "")[:64],
            str(button.get("button_url") or ""),
            button.get("button_style"),
            current,
        ))

    conn.commit()
    conn.close()
    return ad_id


def get_ad_campaign(settings: Settings, ad_id: int):
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT * FROM ad_campaigns WHERE id = ?",
        (ad_id,),
    ).fetchone()
    conn.close()
    return row


def get_next_active_ad_campaign(
    settings: Settings,
    campaign_type: str = AFTER_DOWNLOAD_AD,
):
    conn = db_connect(settings)
    row = conn.execute("""
        SELECT *
        FROM ad_campaigns
        WHERE status = ?
            AND campaign_type = ?
        ORDER BY
            CASE WHEN last_shown_at IS NULL THEN 0 ELSE 1 END ASC,
            last_shown_at ASC,
            id ASC
        LIMIT 1
    """, (ACTIVE, normalize_campaign_type(campaign_type))).fetchone()
    conn.close()
    return row


def list_active_ad_campaigns(
    settings: Settings,
    limit: int | None = None,
    campaign_type: str = AFTER_DOWNLOAD_AD,
):
    conn = db_connect(settings)
    params: list = [ACTIVE, normalize_campaign_type(campaign_type)]
    sql = """
        SELECT *
        FROM ad_campaigns
        WHERE status = ?
            AND campaign_type = ?
        ORDER BY
            CASE WHEN last_shown_at IS NULL THEN 0 ELSE 1 END ASC,
            last_shown_at ASC,
            id ASC
    """

    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(max(1, int(limit)))

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def list_ad_campaigns(
    settings: Settings,
    limit: int = 20,
    campaign_type: str = AFTER_DOWNLOAD_AD,
):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM ad_campaigns
        WHERE campaign_type = ?
        ORDER BY id DESC
        LIMIT ?
    """, (normalize_campaign_type(campaign_type), limit)).fetchall()
    conn.close()
    return rows


def list_current_ad_campaigns(
    settings: Settings,
    limit: int = 50,
    campaign_type: str = AFTER_DOWNLOAD_AD,
):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM ad_campaigns
        WHERE status IN (?, ?)
            AND campaign_type = ?
        ORDER BY id DESC
        LIMIT ?
    """, (ACTIVE, PAUSED, normalize_campaign_type(campaign_type), limit)).fetchall()
    conn.close()
    return rows


def list_ad_buttons(settings: Settings, ad_id: int):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM ad_buttons
        WHERE ad_id = ?
        ORDER BY button_index ASC, id ASC
    """, (ad_id,)).fetchall()

    if rows:
        conn.close()
        return rows

    ad = conn.execute(
        "SELECT id, button_text, button_url, button_style FROM ad_campaigns WHERE id = ?",
        (ad_id,),
    ).fetchone()
    conn.close()

    if not ad or not ad["button_text"] or not ad["button_url"]:
        return []

    return [{
        "id": 0,
        "ad_id": int(ad["id"]),
        "button_index": 0,
        "button_text": ad["button_text"],
        "button_url": ad["button_url"],
        "button_style": ad["button_style"],
    }]


def get_ad_button(settings: Settings, ad_id: int, button_id: int | None):
    buttons = list_ad_buttons(settings, ad_id)

    if not buttons:
        return None

    if not button_id:
        return buttons[0]

    for button in buttons:
        if int(button["id"] or 0) == int(button_id):
            return button

    return None


def get_ad_unique_event_counts(settings: Settings, ad_id: int) -> dict[str, int]:
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT event_type, COUNT(DISTINCT user_id) AS unique_users
        FROM ad_events
        WHERE ad_id = ?
            AND user_id IS NOT NULL
        GROUP BY event_type
    """, (ad_id,)).fetchall()
    conn.close()

    return {
        str(row["event_type"]): int(row["unique_users"] or 0)
        for row in rows
    }


def set_ad_status(settings: Settings, ad_id: int, status: str) -> bool:
    status = status.upper().strip()

    if status not in {ACTIVE, PAUSED, DELETED}:
        return False

    current = now_iso()
    conn = db_connect(settings)
    cur = conn.execute("""
        UPDATE ad_campaigns
        SET status = ?,
            updated_at = ?
        WHERE id = ?
    """, (status, current, ad_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def record_ad_impression(
    settings: Settings,
    *,
    ad_id: int,
    user_id: int | None,
    chat_id: int,
    message_id: int | None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO ad_events (
            ad_id, event_type, user_id, chat_id, message_id, error_text, created_at
        )
        VALUES (?, 'impression', ?, ?, ?, NULL, ?)
    """, (ad_id, user_id, chat_id, message_id, current))

    conn.execute("""
        UPDATE ad_campaigns
        SET impressions_count = impressions_count + 1,
            last_shown_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (current, current, ad_id))

    conn.commit()
    conn.close()


def record_ad_click(
    settings: Settings,
    *,
    ad_id: int,
    user_id: int | None,
    chat_id: int | None,
    message_id: int | None,
) -> None:
    current = now_iso()
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO ad_events (
            ad_id, event_type, user_id, chat_id, message_id, error_text, created_at
        )
        VALUES (?, 'click', ?, ?, ?, NULL, ?)
    """, (ad_id, user_id, chat_id, message_id, current))

    conn.execute("""
        UPDATE ad_campaigns
        SET clicks_count = clicks_count + 1,
            updated_at = ?
        WHERE id = ?
    """, (current, ad_id))

    conn.commit()
    conn.close()


def record_ad_send_failure(
    settings: Settings,
    *,
    ad_id: int,
    user_id: int | None,
    chat_id: int,
    error_text: str | None,
    blocked: bool = False,
) -> None:
    current = now_iso()
    event_type = "blocked" if blocked else "failed"
    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO ad_events (
            ad_id, event_type, user_id, chat_id, message_id, error_text, created_at
        )
        VALUES (?, ?, ?, ?, NULL, ?, ?)
    """, (ad_id, event_type, user_id, chat_id, (error_text or "")[:700], current))

    conn.execute("""
        UPDATE ad_campaigns
        SET failed_count = failed_count + 1,
            blocked_count = blocked_count + ?,
            updated_at = ?
        WHERE id = ?
    """, (1 if blocked else 0, current, ad_id))

    conn.commit()
    conn.close()
