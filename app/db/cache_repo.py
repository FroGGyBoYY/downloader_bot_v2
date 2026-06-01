from typing import Optional

from app.config import Settings
from app.db.database import db_connect
from app.db.users_repo import now_iso


def get_cached_item(settings: Settings, cache_key: str):
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT * FROM media_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    conn.close()
    return row


def get_cached_bundle(settings: Settings, bundle_key: str):
    conn = db_connect(settings)
    rows = conn.execute("""
        SELECT *
        FROM media_cache
        WHERE bundle_key = ?
        ORDER BY item_index ASC
    """, (bundle_key,)).fetchall()
    conn.close()
    return rows


def touch_cache_item(settings: Settings, cache_key: str) -> None:
    conn = db_connect(settings)
    conn.execute("""
        UPDATE media_cache
        SET hits = hits + 1,
            last_hit_at = ?
        WHERE cache_key = ?
    """, (now_iso(), cache_key))
    conn.commit()
    conn.close()


def touch_cache_bundle(settings: Settings, bundle_key: str) -> None:
    conn = db_connect(settings)
    conn.execute("""
        UPDATE media_cache
        SET hits = hits + 1,
            last_hit_at = ?
        WHERE bundle_key = ?
    """, (now_iso(), bundle_key))
    conn.commit()
    conn.close()


def save_cached_item(
    settings: Settings,
    *,
    cache_key: str,
    bundle_key: str,
    source_key: str,
    variant_key: str,
    platform: str,
    content_type: str,
    media_type: str,
    original_url: str,
    resolved_url: Optional[str],
    title: Optional[str],
    author: Optional[str],
    item_index: int,
    item_total: int,
    tg_file_id: str,
    tg_file_unique_id: Optional[str],
    tg_send_type: str,
    file_size: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[int] = None,
    quality: Optional[int] = None,
    audio_lang: Optional[str] = None,
    album_title: Optional[str] = None,
) -> None:
    current = now_iso()

    conn = db_connect(settings)

    conn.execute("""
        INSERT INTO media_cache (
            cache_key, bundle_key, source_key, variant_key,
            platform, content_type, media_type,
            original_url, resolved_url,
            title, author, album_title,
            item_index, item_total,
            tg_file_id, tg_file_unique_id, tg_send_type,
            file_size, width, height, duration,
            quality, audio_lang,
            created_at, last_hit_at, hits
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
            (SELECT hits FROM media_cache WHERE cache_key = ?), 0
        ))
        ON CONFLICT(cache_key) DO UPDATE SET
            bundle_key = excluded.bundle_key,
            source_key = excluded.source_key,
            variant_key = excluded.variant_key,
            platform = excluded.platform,
            content_type = excluded.content_type,
            media_type = excluded.media_type,
            original_url = excluded.original_url,
            resolved_url = excluded.resolved_url,
            title = excluded.title,
            author = excluded.author,
            album_title = excluded.album_title,
            item_index = excluded.item_index,
            item_total = excluded.item_total,
            tg_file_id = excluded.tg_file_id,
            tg_file_unique_id = excluded.tg_file_unique_id,
            tg_send_type = excluded.tg_send_type,
            file_size = excluded.file_size,
            width = excluded.width,
            height = excluded.height,
            duration = excluded.duration,
            quality = excluded.quality,
            audio_lang = excluded.audio_lang,
            last_hit_at = excluded.last_hit_at
    """, (
        cache_key,
        bundle_key,
        source_key,
        variant_key,
        platform,
        content_type,
        media_type,
        original_url,
        resolved_url,
        title,
        author,
        album_title,
        item_index,
        item_total,
        tg_file_id,
        tg_file_unique_id,
        tg_send_type,
        file_size,
        width,
        height,
        duration,
        quality,
        audio_lang,
        current,
        current,
        cache_key,
    ))

    conn.commit()
    conn.close()
