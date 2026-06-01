from urllib.parse import urlparse, urlunparse


def clean_download_url(url: str | None) -> str | None:
    if not url:
        return url

    parsed = urlparse(str(url))
    host = parsed.netloc.lower()
    path = parsed.path

    # TikTok часто ломается на resolved URL с _r/_t.
    # Для скачивания оставляем только чистый canonical URL.
    if host.endswith("tiktok.com") and (
        "/video/" in path
        or "/photo/" in path
        or "/music/" in path
    ):
        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc,
                parsed.path,
                "",
                "",
                "",
            )
        )

    if host.endswith("instagram.com") and "/stories/" in path.lower():
        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc,
                parsed.path if parsed.path.endswith("/") else parsed.path + "/",
                "",
                "",
                "",
            )
        )

    return url
