import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "nano.env"


def _load_env_dict() -> dict[str, str]:
    """
    Читаем настройки только из nano.env в папке проекта.
    Не берём BOT_TOKEN из Windows PATH / User env / Machine env.
    """
    if not ENV_FILE.exists():
        raise FileNotFoundError(f"nano.env not found: {ENV_FILE}")

    raw = dotenv_values(ENV_FILE)

    return {
        str(k): str(v).strip()
        for k, v in raw.items()
        if k and v is not None
    }


ENV = _load_env_dict()


def _get_str(name: str, default: str = "") -> str:
    return ENV.get(name, default).strip()


def _get_bool(name: str, default: bool = False) -> bool:
    value = ENV.get(name)

    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = ENV.get(name)

    if not value:
        return default

    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _get_path(name: str, default: str) -> Path:
    raw = _get_str(name, default)

    path = Path(raw)

    if not path.is_absolute():
        path = BASE_DIR / path

    return path


def _get_optional_path(name: str) -> Optional[Path]:
    raw = _get_str(name, "")

    if not raw:
        return None

    path = Path(raw)

    if not path.is_absolute():
        path = BASE_DIR / path

    return path


def _get_int_set(name: str) -> set[int]:
    raw = _get_str(name, "")
    ids: set[int] = set()

    for item in raw.split(","):
        item = item.strip()

        if item.isdigit():
            ids.add(int(item))

    return ids


def _get_admin_ids() -> set[int]:
    return _get_int_set("ADMIN_IDS")


def _get_cookie_alert_admin_ids() -> set[int]:
    ids = _get_int_set("COOKIE_ALERT_ADMIN_IDS")
    return ids or _get_admin_ids()


def _get_helper_bot_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}

    for index in range(1, 11):
        token = _get_str(f"HELPER_BOT_{index}_TOKEN", "")

        if token:
            tokens[f"helper_{index}"] = token

    return tokens


def _get_default_cookie_path(filename: str) -> Path:
    return BASE_DIR / "secrets" / "cookies" / filename


def _get_cookie_slot_paths(
    *,
    env_prefix: str,
    legacy_env_name: str,
    legacy_default_filename: str,
) -> tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]:
    prefix = env_prefix.upper()
    base = env_prefix.lower()

    slot_1 = (
        _get_optional_path(f"{prefix}_COOKIES_1_PATH")
        or _get_optional_path(legacy_env_name)
        or _get_default_cookie_path(f"{base}_cookies_1.txt")
        or _get_default_cookie_path(legacy_default_filename)
    )

    return (
        None,
        slot_1,
        _get_optional_path(f"{prefix}_COOKIES_2_PATH")
        or _get_default_cookie_path(f"{base}_cookies_2.txt"),
        _get_optional_path(f"{prefix}_COOKIES_3_PATH")
        or _get_default_cookie_path(f"{base}_cookies_3.txt"),
    )


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    env_file: Path

    bot_token: str
    bot_username_text: str
    admin_ids: set[int]
    cookie_alert_admin_ids: set[int]
    helper_bot_tokens: dict[str, str]

    db_path: Path

    worker_count: int
    daily_limit: int
    daily_admin_report_hour: int
    scheduled_ad_interval_hours: int
    cookie_health_check_interval_hours: int
    maintenance_default_text: str
    welcome_photo_path: Optional[Path]

    use_local_bot_api: bool
    bot_api_base_url: str

    max_file_size_mb: int
    fast_mode_max_mb: int

    send_read_timeout: int
    send_write_timeout: int
    send_connect_timeout: int
    send_pool_timeout: int

    local_tz_hours: int

    youtube_cookies_path: Optional[Path]
    instagram_cookies_path: Optional[Path]
    tiktok_cookies_path: Optional[Path]
    pinterest_cookies_path: Optional[Path]

    youtube_cookie_slot_paths: tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]
    instagram_cookie_slot_paths: tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]
    tiktok_cookie_slot_paths: tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]
    pinterest_cookie_slot_paths: tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]

    deno_path: Optional[Path]
    youtube_proxy_url: str

    log_level: str

    allowed_domains: tuple[str, ...]


def load_settings() -> Settings:
    return Settings(
        base_dir=BASE_DIR,
        env_file=ENV_FILE,

        bot_token=_get_str("BOT_TOKEN", ""),
        bot_username_text=_get_str("BOT_USERNAME_TEXT", "@Top_Savers_bot"),
        admin_ids=_get_admin_ids(),
        cookie_alert_admin_ids=_get_cookie_alert_admin_ids(),
        helper_bot_tokens=_get_helper_bot_tokens(),

        db_path=_get_path("DB_PATH", "data/bot_v2.db"),

        worker_count=_get_int("WORKER_COUNT", 3),
        daily_limit=_get_int("DAILY_LIMIT", 100),
        daily_admin_report_hour=_get_int("DAILY_ADMIN_REPORT_HOUR", 9),
        scheduled_ad_interval_hours=_get_int("SCHEDULED_AD_INTERVAL_HOURS", 8),
        cookie_health_check_interval_hours=_get_int("COOKIE_HEALTH_CHECK_INTERVAL_HOURS", 6),
        maintenance_default_text=_get_str(
            "MAINTENANCE_DEFAULT_TEXT",
            "бот на обслуживании осталось примерно 10 минут",
        ),
        welcome_photo_path=_get_optional_path("WELCOME_PHOTO_PATH"),

        use_local_bot_api=_get_bool("USE_LOCAL_BOT_API", False),
        bot_api_base_url=_get_str("BOT_API_BASE_URL", "http://127.0.0.1:8081").rstrip("/"),

        max_file_size_mb=_get_int("MAX_FILE_SIZE_MB", 48),
        fast_mode_max_mb=_get_int("FAST_MODE_MAX_MB", 45),

        send_read_timeout=_get_int("SEND_READ_TIMEOUT", 600),
        send_write_timeout=_get_int("SEND_WRITE_TIMEOUT", 1800),
        send_connect_timeout=_get_int("SEND_CONNECT_TIMEOUT", 30),
        send_pool_timeout=_get_int("SEND_POOL_TIMEOUT", 30),

        local_tz_hours=_get_int("LOCAL_TZ_HOURS", 7),

        youtube_cookies_path=_get_optional_path("YOUTUBE_COOKIES_PATH"),
        instagram_cookies_path=_get_optional_path("INSTAGRAM_COOKIES_PATH"),
        tiktok_cookies_path=_get_optional_path("TIKTOK_COOKIES_PATH"),
        pinterest_cookies_path=_get_optional_path("PINTEREST_COOKIES_PATH"),

        youtube_cookie_slot_paths=_get_cookie_slot_paths(
            env_prefix="YOUTUBE",
            legacy_env_name="YOUTUBE_COOKIES_PATH",
            legacy_default_filename="youtube_cookies.txt",
        ),
        instagram_cookie_slot_paths=_get_cookie_slot_paths(
            env_prefix="INSTAGRAM",
            legacy_env_name="INSTAGRAM_COOKIES_PATH",
            legacy_default_filename="instagram_cookies.txt",
        ),
        tiktok_cookie_slot_paths=_get_cookie_slot_paths(
            env_prefix="TIKTOK",
            legacy_env_name="TIKTOK_COOKIES_PATH",
            legacy_default_filename="tiktok_cookies.txt",
        ),
        pinterest_cookie_slot_paths=_get_cookie_slot_paths(
            env_prefix="PINTEREST",
            legacy_env_name="PINTEREST_COOKIES_PATH",
            legacy_default_filename="pinterest_cookies.txt",
        ),

        deno_path=_get_optional_path("DENO_PATH"),
        youtube_proxy_url=_get_str("YOUTUBE_PROXY_URL", ""),

        log_level=_get_str("LOG_LEVEL", "INFO").upper(),

        allowed_domains=(
            "youtube.com",
            "youtu.be",
            "tiktok.com",
            "instagram.com",
            "pinterest.com",
            "pin.it",
        ),
    )
