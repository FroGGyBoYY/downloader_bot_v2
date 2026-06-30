from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.config import Settings
from app.db.cookie_auth_repo import normalize_cookie_platform
from app.db.proxy_pool_repo import (
    get_next_proxy,
    is_proxy_error,
    mark_proxy_failed,
    mark_proxy_success,
)


logger = logging.getLogger(__name__)

T = TypeVar("T")

PROXY_ROTATION_PLATFORMS = {"youtube", "instagram", "tiktok"}
DEFAULT_MAX_PROXY_ATTEMPTS = 6

PLATFORM_ACCESS_ERROR_MARKERS = (
    "video unavailable",
    "this content isn't available",
    "this content isn’t available",
    "requested content is not available",
    "not available in your country",
    "not available from your location",
    "geo restricted",
    "georestricted",
    "429",
    "too many requests",
    "rate-limit",
    "rate limit",
    "http error 403",
    "http error 401",
    "403 forbidden",
    "401 unauthorized",
    "forbidden",
    "google sorry",
    "captcha",
    "sign in to confirm",
    "login required",
    "http redirect to login page",
    "accounts/login",
    "unsupported url 'https://www.instagram.com/accounts/login",
    "ip address is blocked",
    "blocked from accessing this post",
    "download completed but no files were created",
    "download completed but no media items were returned",
    "yt-dlp returned empty metadata",
)


@dataclass(frozen=True)
class ProxyRotationResult:
    value: T
    proxy_id: int | None
    proxy_url: str | None


def is_proxy_retryable_error(error: object, platform: str | None = None) -> bool:
    """Return True when trying another proxy may fix the current platform error."""
    if is_proxy_error(error):
        return True

    normalized = normalize_cookie_platform(platform)
    if normalized not in PROXY_ROTATION_PLATFORMS:
        return False

    text = str(error or "").casefold()
    return any(marker in text for marker in PLATFORM_ACCESS_ERROR_MARKERS)


def run_with_proxy_rotation_sync(
    *,
    settings: Settings,
    platform: str | None,
    operation: Callable[[str | None], T],
    operation_name: str,
    max_attempts: int = DEFAULT_MAX_PROXY_ATTEMPTS,
) -> ProxyRotationResult[T]:
    """
    Run a blocking platform operation through the proxy pool.

    The operation receives a proxy URL or None. A proxy is marked DEAD only for
    transport/auth proxy failures. Platform access errors are recorded as a
    failed attempt but keep the proxy active for other media.
    """
    normalized = normalize_cookie_platform(platform)
    if normalized not in PROXY_ROTATION_PLATFORMS:
        return ProxyRotationResult(value=operation(None), proxy_id=None, proxy_url=None)

    tried: set[int] = set()
    last_error: Exception | None = None
    attempts = max(1, int(max_attempts or DEFAULT_MAX_PROXY_ATTEMPTS))

    for _ in range(attempts):
        proxy = get_next_proxy(settings, exclude_ids=tried)
        if not proxy:
            break

        proxy_id = int(proxy.get("id") or 0)
        proxy_url = str(proxy.get("proxy_url") or "").strip()
        if not proxy_id or not proxy_url:
            break

        tried.add(proxy_id)

        try:
            value = operation(proxy_url)
        except Exception as exc:
            last_error = exc
            if not is_proxy_retryable_error(exc, normalized):
                mark_proxy_failed(settings, proxy_id, str(exc), dead=False)
                raise

            dead = is_proxy_error(exc)
            mark_proxy_failed(settings, proxy_id, str(exc), dead=dead)
            logger.warning(
                "Proxy retry | operation=%s platform=%s proxy_id=%s dead=%s error=%s",
                operation_name,
                normalized,
                proxy_id,
                dead,
                str(exc)[:240],
            )
            continue

        mark_proxy_success(settings, proxy_id)
        logger.info(
            "Proxy success | operation=%s platform=%s proxy_id=%s",
            operation_name,
            normalized,
            proxy_id,
        )
        return ProxyRotationResult(value=value, proxy_id=proxy_id, proxy_url=proxy_url)

    if last_error is not None:
        raise last_error

    logger.info(
        "Proxy pool empty, running without pool proxy | operation=%s platform=%s",
        operation_name,
        normalized,
    )
    return ProxyRotationResult(value=operation(None), proxy_id=None, proxy_url=None)
