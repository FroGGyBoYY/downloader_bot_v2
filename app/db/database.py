import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings


def db_connect(settings: Settings) -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        settings.db_path,
        timeout=30,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_db(settings: Settings) -> None:
    conn = db_connect(settings)
    cur = conn.cursor()
    current = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cur.execute("PRAGMA journal_mode = WAL")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        language_code TEXT,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        requests_count INTEGER NOT NULL DEFAULT 0,
        downloads_count INTEGER NOT NULL DEFAULT 0,
        cache_hits_count INTEGER NOT NULL DEFAULT 0,
        subscription_status TEXT NOT NULL DEFAULT 'free',
        subscription_until TEXT,
        is_premium INTEGER NOT NULL DEFAULT 0,
        is_friend INTEGER NOT NULL DEFAULT 0,
        is_banned INTEGER NOT NULL DEFAULT 0
    )
    """)

    add_column_if_missing(conn, "users", "language_code", "TEXT")
    add_column_if_missing(conn, "users", "requests_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "downloads_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "cache_hits_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "subscription_status", "TEXT NOT NULL DEFAULT 'free'")
    add_column_if_missing(conn, "users", "subscription_until", "TEXT")
    add_column_if_missing(conn, "users", "is_premium", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "is_friend", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "is_banned", "INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        event_value TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        username TEXT,
        chat_type TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        added_by_user_id INTEGER,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        last_activity_at TEXT,
        requests_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS download_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT,
        language_code TEXT,

        original_url TEXT NOT NULL,
        resolved_url TEXT,
        platform TEXT,
        content_type TEXT,
        action TEXT,

        source_key TEXT,
        variant_key TEXT,
        bundle_key TEXT,

        title TEXT,
        status TEXT NOT NULL,
        cache_status TEXT,

        items_total INTEGER NOT NULL DEFAULT 0,
        items_sent INTEGER NOT NULL DEFAULT 0,

        requested_quality INTEGER,
        requested_audio_lang TEXT,

        error_type TEXT,
        error_text TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS media_cache (
        cache_key TEXT PRIMARY KEY,

        bundle_key TEXT,
        source_key TEXT NOT NULL,
        variant_key TEXT NOT NULL,

        platform TEXT,
        content_type TEXT,
        media_type TEXT NOT NULL,

        original_url TEXT,
        resolved_url TEXT,

        title TEXT,
        author TEXT,
        album_title TEXT,

        item_index INTEGER NOT NULL DEFAULT 0,
        item_total INTEGER NOT NULL DEFAULT 1,

        tg_file_id TEXT NOT NULL,
        tg_file_unique_id TEXT,
        tg_send_type TEXT NOT NULL,

        file_size INTEGER,
        width INTEGER,
        height INTEGER,
        duration INTEGER,

        quality INTEGER,
        audio_lang TEXT,

        created_at TEXT NOT NULL,
        last_hit_at TEXT NOT NULL,
        hits INTEGER NOT NULL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS download_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        request_id INTEGER NOT NULL,
        cache_key TEXT,

        item_index INTEGER NOT NULL DEFAULT 0,
        media_type TEXT NOT NULL,

        status TEXT NOT NULL,
        cache_status TEXT,

        tg_file_id TEXT,
        tg_send_type TEXT,

        file_size INTEGER,
        width INTEGER,
        height INTEGER,
        duration INTEGER,

        error_type TEXT,
        error_text TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        FOREIGN KEY(request_id) REFERENCES download_requests(id)
    )
    """)

    add_column_if_missing(conn, "media_cache", "album_title", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cookie_account_stats (
        platform TEXT NOT NULL,
        slot INTEGER NOT NULL,
        current_count INTEGER NOT NULL DEFAULT 0,
        total_count INTEGER NOT NULL DEFAULT 0,
        lifetime_sum INTEGER NOT NULL DEFAULT 0,
        lifetime_count INTEGER NOT NULL DEFAULT 0,
        last_replaced_at TEXT,
        last_started_at TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(platform, slot)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT NOT NULL,
        target TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        note TEXT,
        added_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_type TEXT,
        error_text TEXT,
        traceback_text TEXT,
        update_type TEXT,
        user_id INTEGER,
        chat_id INTEGER,
        update_preview TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        full_name TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        report_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        campaign_type TEXT NOT NULL DEFAULT 'after_download',

        source_chat_id INTEGER NOT NULL,
        source_message_id INTEGER NOT NULL,
        source_type TEXT,

        button_text TEXT,
        button_url TEXT,
        button_style TEXT,

        created_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_shown_at TEXT,

        impressions_count INTEGER NOT NULL DEFAULT 0,
        clicks_count INTEGER NOT NULL DEFAULT 0,
        blocked_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0
    )
    """)

    add_column_if_missing(conn, "ad_campaigns", "campaign_type", "TEXT NOT NULL DEFAULT 'after_download'")
    add_column_if_missing(conn, "ad_campaigns", "source_type", "TEXT")
    add_column_if_missing(conn, "ad_campaigns", "button_text", "TEXT")
    add_column_if_missing(conn, "ad_campaigns", "button_url", "TEXT")
    add_column_if_missing(conn, "ad_campaigns", "button_style", "TEXT")
    add_column_if_missing(conn, "ad_campaigns", "last_shown_at", "TEXT")
    add_column_if_missing(conn, "ad_campaigns", "impressions_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "ad_campaigns", "clicks_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "ad_campaigns", "blocked_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "ad_campaigns", "failed_count", "INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        user_id INTEGER,
        chat_id INTEGER,
        message_id INTEGER,
        error_text TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(ad_id) REFERENCES ad_campaigns(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ad_buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad_id INTEGER NOT NULL,
        button_index INTEGER NOT NULL DEFAULT 0,
        button_text TEXT NOT NULL,
        button_url TEXT NOT NULL,
        button_style TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(ad_id) REFERENCES ad_campaigns(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS required_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        resource_type TEXT NOT NULL,

        target_chat TEXT,
        checker_bot_key TEXT NOT NULL DEFAULT 'main',
        button_text TEXT NOT NULL,
        button_url TEXT NOT NULL,
        button_style TEXT,

        created_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        impressions_count INTEGER NOT NULL DEFAULT 0,
        clicks_count INTEGER NOT NULL DEFAULT 0,
        passes_count INTEGER NOT NULL DEFAULT 0,
        fails_count INTEGER NOT NULL DEFAULT 0,
        check_errors_count INTEGER NOT NULL DEFAULT 0
    )
    """)

    add_column_if_missing(conn, "required_resources", "checker_bot_key", "TEXT NOT NULL DEFAULT 'main'")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS required_resource_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        user_id INTEGER,
        chat_id INTEGER,
        error_text TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(resource_id) REFERENCES required_resources(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS required_resource_user_state (
        resource_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        satisfied_at TEXT NOT NULL,
        last_checked_at TEXT NOT NULL,
        satisfied_by TEXT NOT NULL,
        PRIMARY KEY(resource_id, user_id),
        FOREIGN KEY(resource_id) REFERENCES required_resources(id)
    )
    """)

    for platform in ("youtube", "instagram", "tiktok", "pinterest"):
        cur.execute("""
            INSERT OR IGNORE INTO bot_settings (key, value, updated_at)
            VALUES (?, '0', ?)
        """, (f"{platform}_auth_slot", current))

        for slot in (0, 1, 2, 3):
            cur.execute("""
                INSERT OR IGNORE INTO cookie_account_stats (
                    platform, slot, current_count, total_count,
                    lifetime_sum, lifetime_count,
                    last_replaced_at, last_started_at, updated_at
                )
                VALUES (?, ?, 0, 0, 0, 0, NULL, ?, ?)
            """, (platform, slot, current, current))

    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_language ON users(language_code)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_friend ON users(is_friend)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_events_user ON user_events(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_events_created ON user_events(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_groups_status ON bot_groups(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_groups_last_seen ON bot_groups(last_seen)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_groups_activity ON bot_groups(last_activity_at)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_user_created ON download_requests(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_platform_created ON download_requests(platform, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_content_created ON download_requests(content_type, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_status_created ON download_requests(status, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_source_key ON download_requests(source_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_bundle_key ON download_requests(bundle_key)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_cache_source ON media_cache(source_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_cache_bundle ON media_cache(bundle_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_cache_platform ON media_cache(platform)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_cache_hits ON media_cache(hits)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_download_items_request ON download_items(request_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_download_items_cache ON download_items(cache_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_download_items_status ON download_items(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cookie_stats_platform_slot ON cookie_account_stats(platform, slot)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_actions_created ON admin_actions(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_users_created ON admin_users(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_errors_created ON bot_errors(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_errors_type ON bot_errors(error_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_reports_created ON user_reports(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_reports_status ON user_reports(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_reports_user ON user_reports(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_campaigns_status ON ad_campaigns(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_campaigns_type_status ON ad_campaigns(campaign_type, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_campaigns_last_shown ON ad_campaigns(last_shown_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_buttons_ad_index ON ad_buttons(ad_id, button_index)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_events_ad_created ON ad_events(ad_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_events_user_created ON ad_events(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_required_resources_status ON required_resources(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_required_events_resource_created ON required_resource_events(resource_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_required_events_user_created ON required_resource_events(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_required_state_user ON required_resource_user_state(user_id)")

    conn.commit()
    conn.close()
