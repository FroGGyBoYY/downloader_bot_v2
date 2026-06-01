import logging
from urllib.parse import urlparse

import httpx


logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


def resolve_redirect_url(url: str, timeout: float = 12.0) -> str:
    """
    Раскрывает короткие ссылки:
    - vt.tiktok.com -> tiktok.com/@user/video/... или /photo/... или /music/...
    - pin.it -> pinterest.com/pin/...
    Если редирект не удалось раскрыть, возвращает исходный URL.
    """
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=DEFAULT_HEADERS,
        ) as client:
            response = client.get(url)

        final_url = str(response.url)

        original_parsed = urlparse(url)
        final_parsed = urlparse(final_url)

        if (
            original_parsed.netloc.lower().endswith("instagram.com")
            and "/stories/" in original_parsed.path.lower()
            and final_parsed.netloc.lower().endswith("instagram.com")
            and final_parsed.path.lower().startswith("/accounts/login")
        ):
            logger.info("Instagram story resolve ended at login page; keeping original URL | url=%s", url)
            return url

        if final_url and final_url != url:
            logger.info("URL resolved | original=%s | resolved=%s", url, final_url)
            return final_url

    except Exception as e:
        logger.warning("URL resolve failed | url=%s | error=%s", url, e)

    return url
