from typing import Optional

from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def create_download_request(
    settings: Settings,
    *,
    user_id: int,
    username: Optional[str],
    full_name: str,
    language_code: Optional[str],
    original_url: str,
    resolved_url: Optional[str],
    platform: str,
    content_type: str,
    action: str,
    source_key: Optional[str],
    variant_key: Optional[str],
    bundle_key: Optional[str],
    title: Optional[str],
    requested_quality: Optional[int] = None,
    requested_audio_lang: Optional[str] = None,
    status: str = "created",
    cache_status: Optional[str] = None,
) -> int:
    current = now_iso()

    conn = db_connect(settings)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO download_requests (
            user_id, username, full_name, language_code,
            original_url, resolved_url, platform, content_type, action,
            source_key, variant_key, bundle_key,
            title, status, cache_status,
            requested_quality, requested_audio_lang,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        username,
        full_name,
        language_code,
        original_url,
        resolved_url,
        platform,
        content_type,
        action,
        source_key,
        variant_key,
        bundle_key,
        title,
        status,
        cache_status,
        requested_quality,
        requested_audio_lang,
        current,
        current,
    ))

    request_id = int(cur.lastrowid)

    conn.commit()
    conn.close()

    return request_id


def update_download_request(
    settings: Settings,
    request_id: int,
    **fields,
) -> None:
    if not fields:
        return

    fields["updated_at"] = now_iso()

    keys = list(fields.keys())
    values = [fields[key] for key in keys]
    values.append(request_id)

    set_clause = ", ".join([f"{key} = ?" for key in keys])

    conn = db_connect(settings)
    conn.execute(
        f"UPDATE download_requests SET {set_clause} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def add_download_item(
    settings: Settings,
    *,
    request_id: int,
    cache_key: Optional[str],
    item_index: int,
    media_type: str,
    status: str,
    cache_status: Optional[str] = None,
    tg_file_id: Optional[str] = None,
    tg_send_type: Optional[str] = None,
    file_size: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[int] = None,
    error_type: Optional[str] = None,
    error_text: Optional[str] = None,
) -> int:
    current = now_iso()

    conn = db_connect(settings)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO download_items (
            request_id, cache_key, item_index, media_type,
            status, cache_status, tg_file_id, tg_send_type,
            file_size, width, height, duration,
            error_type, error_text, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request_id,
        cache_key,
        item_index,
        media_type,
        status,
        cache_status,
        tg_file_id,
        tg_send_type,
        file_size,
        width,
        height,
        duration,
        error_type,
        error_text,
        current,
        current,
    ))

    item_id = int(cur.lastrowid)

    conn.commit()
    conn.close()

    return item_id