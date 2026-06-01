from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlparse

import yt_dlp

from app.config import ENV, Settings, load_settings
from app.db.admin_repo import get_all_admin_ids
from app.db.cookie_auth_repo import get_auth_slot
from app.db.database import init_db
from app.db.proxy_pool_repo import (
    get_next_proxy,
    is_proxy_error,
    mark_proxy_failed,
    mark_proxy_success,
    mask_proxy,
)
from app.downloader.content_types import ContentType, DownloadAction, Platform
from app.downloader.cookies import apply_platform_cookies
from app.downloader.download_engine import DownloadedMedia, download_media_bundle
from app.downloader.routing import RouteDecision

try:
    from ytmusicapi import YTMusic
except ImportError:  # pragma: no cover - optional dependency on older installs
    YTMusic = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class AudioNotFoundError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return str(ENV.get(name, default) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _telegram_send_message_url(settings: Settings) -> str:
    token = str(getattr(settings, "bot_token", "") or _env("BOT_TOKEN", "")).strip()
    if not token:
        return ""
    base_url = str(getattr(settings, "bot_api_base_url", "") or "").rstrip("/")
    if bool(getattr(settings, "use_local_bot_api", False)) and base_url:
        return f"{base_url}/bot{token}/sendMessage"
    return f"https://api.telegram.org/bot{token}/sendMessage"


def _notify_admins_proxy_dead(settings: Settings, proxy_id: int, proxy_url: str, error: object) -> None:
    endpoint = _telegram_send_message_url(settings)
    if not endpoint:
        logger.warning("Proxy DEAD notification skipped: bot token is empty")
        return

    try:
        admin_ids = sorted(get_all_admin_ids(settings))
    except Exception as admin_error:
        logger.warning("Proxy DEAD notification skipped: failed to load admins: %s", admin_error)
        return

    if not admin_ids:
        logger.warning("Proxy DEAD notification skipped: no admin ids configured")
        return

    reason = " ".join(str(error or "unknown error").split())
    if len(reason) > 900:
        reason = f"{reason[:900]}..."
    text = (
        "Proxy marked DEAD\n"
        "Service: YouTube Music\n"
        f"ID: #{proxy_id}\n"
        f"Proxy: {mask_proxy(proxy_url)}\n"
        f"Reason: {reason}"
    )
    body_template = {"text": text, "disable_web_page_preview": True}
    for admin_id in admin_ids:
        body = json.dumps({**body_template, "chat_id": admin_id}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read()
        except Exception as notify_error:
            logger.warning("Failed to notify admin %s about dead proxy: %s", admin_id, notify_error)


def _source_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("source_candidate")
    return value if isinstance(value, dict) else {}


def _artist_names(payload: dict[str, Any]) -> str:
    artists = payload.get("artists")
    if isinstance(artists, list):
        names = [str(item).strip() for item in artists if str(item).strip()]
        if names:
            return ", ".join(names)
    return str(payload.get("artist") or "").strip()


def _search_query(payload: dict[str, Any]) -> str:
    candidate = _source_candidate(payload)
    query = str(candidate.get("search_query") or "").strip()
    if query:
        return query

    title = str(payload.get("title") or "").strip()
    artists = _artist_names(payload)
    return f"{artists} {title}".strip()


def _is_youtube_music_search_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() == "music.youtube.com" and parsed.path.rstrip("/") == "/search"


def _query_from_youtube_music_search_url(url: str) -> str:
    parsed = urlparse(url)
    query_values = parse_qs(parsed.query).get("q") or []
    if not query_values:
        return ""
    return unquote_plus(str(query_values[0])).strip()


def _download_url(payload: dict[str, Any]) -> str:
    candidate = _source_candidate(payload)
    url = str(candidate.get("url") or "").strip()
    if url:
        return url

    query = _search_query(payload)
    if not query:
        raise ValueError("source_candidate.url or title/artists are required")
    return f"https://music.youtube.com/search?q={quote_plus(query)}"


def _dedupe_urls(urls: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _ytmusicapi_candidate_urls(query: str, *, limit: int = 5) -> list[str]:
    if YTMusic is None:
        return []

    urls: list[str] = []
    client = YTMusic()
    for search_filter in ("songs", "videos"):
        try:
            results = client.search(query, filter=search_filter, limit=limit)
        except Exception as error:
            logger.warning("YouTube Music search failed | filter=%s error=%s", search_filter, error)
            continue

        for item in results:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("videoId") or "").strip()
            if video_id:
                urls.append(f"https://music.youtube.com/watch?v={video_id}")
            if len(urls) >= limit:
                break
        if len(urls) >= limit:
            break

    return _dedupe_urls(urls)


def _yt_dlp_search_candidate_urls(
    settings: Settings,
    query: str,
    *,
    platform_auth_slot: int | None,
    limit: int = 5,
) -> list[str]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }
    ydl_opts = apply_platform_cookies(
        settings,
        "https://music.youtube.com/watch?v=search",
        ydl_opts,
        platform_auth_slot=platform_auth_slot,
        proxy_url_override="",
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max(1, limit)}:{query}", download=False)

    entries = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(entries, list):
        return []

    urls: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        webpage_url = str(entry.get("webpage_url") or entry.get("original_url") or "").strip()
        if webpage_url.startswith(("http://", "https://")):
            urls.append(webpage_url)
            continue
        video_id = str(entry.get("id") or entry.get("url") or "").strip()
        if video_id and not video_id.startswith(("http://", "https://")):
            urls.append(f"https://music.youtube.com/watch?v={video_id}")
        elif video_id.startswith(("http://", "https://")):
            urls.append(video_id)

    return _dedupe_urls(urls)


def _candidate_download_urls(
    settings: Settings,
    payload: dict[str, Any],
    initial_url: str,
    *,
    platform_auth_slot: int | None,
) -> list[str]:
    if not _is_youtube_music_search_url(initial_url):
        return [initial_url]

    query = _query_from_youtube_music_search_url(initial_url) or _search_query(payload)
    if not query:
        raise ValueError("YouTube Music search query is empty")

    logger.info("Resolving YouTube Music query before download | query=%s", query)
    urls = _ytmusicapi_candidate_urls(query, limit=3)
    if urls:
        return urls

    return _yt_dlp_search_candidate_urls(
        settings,
        query,
        platform_auth_slot=platform_auth_slot,
        limit=3,
    )


def _youtube_slot_order(settings: Settings) -> list[int | None]:
    try:
        active_slot = int(get_auth_slot(settings, "youtube"))
    except Exception:
        active_slot = 0

    slots: list[int | None] = [active_slot, 0, 1, 2, 3]
    result: list[int | None] = []
    seen: set[int | None] = set()
    for slot in slots:
        if slot in seen:
            continue
        seen.add(slot)
        result.append(slot)
    return result


def _resolve_youtube_music_result(
    settings: Settings,
    payload: dict[str, Any],
    url: str,
    *,
    platform_auth_slot: int | None,
) -> str:
    if not _is_youtube_music_search_url(url):
        return url

    query = _query_from_youtube_music_search_url(url) or _search_query(payload)
    if not query:
        raise ValueError("YouTube Music search query is empty")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
    }
    ydl_opts = apply_platform_cookies(
        settings,
        "https://music.youtube.com/watch?v=search",
        ydl_opts,
        platform_auth_slot=platform_auth_slot,
        proxy_url_override="",
    )

    logger.info("Resolving YouTube Music query before download | query=%s", query)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)

    entries = info.get("entries") if isinstance(info, dict) else None
    if isinstance(entries, list):
        match = next((entry for entry in entries if isinstance(entry, dict)), None)
    elif isinstance(info, dict):
        match = info
    else:
        match = None

    if not match:
        raise RuntimeError("YouTube Music search returned no usable results")

    webpage_url = str(match.get("webpage_url") or match.get("original_url") or "").strip()
    if webpage_url.startswith(("http://", "https://")):
        return webpage_url

    video_id = str(match.get("id") or match.get("url") or "").strip()
    if video_id and not video_id.startswith(("http://", "https://")):
        return f"https://music.youtube.com/watch?v={video_id}"

    if video_id.startswith(("http://", "https://")):
        return video_id

    raise RuntimeError("YouTube Music search result has no playable URL")


def _route_for_audio(payload: dict[str, Any], url: str) -> RouteDecision:
    return RouteDecision(
        platform=Platform.YOUTUBE,
        content_type=ContentType.AUDIO,
        action=DownloadAction.DOWNLOAD_AUDIO,
        title=str(payload.get("title") or "YouTube Music audio"),
        routing_url=url,
        url_reason="spotify_audio_api_bridge",
        url_confidence=1.0,
        metadata_status="not_used",
    )


def _pick_audio(items: list[DownloadedMedia]) -> DownloadedMedia | None:
    for item in items:
        if item.media_type == "audio" and item.path.exists():
            return item
    for item in items:
        if item.path.exists():
            return item
    return None


def _cache_key(payload: dict[str, Any], url: str, item: DownloadedMedia) -> str:
    candidate = _source_candidate(payload)
    source = str(candidate.get("source") or "youtube_music").strip()
    source_id = str(candidate.get("source_id") or "").strip()
    spotify_id = str(payload.get("spotify_id") or "").strip()
    if source_id and spotify_id:
        return f"{source}:{source_id}:{spotify_id}"
    if spotify_id:
        return f"{source}:{spotify_id}"
    return f"{source}:{uuid.uuid5(uuid.NAMESPACE_URL, url)}:{item.path.name}"


class AudioApiHandler(BaseHTTPRequestHandler):
    server_version = "TopSaversAudioAPI/1.0"

    @property
    def settings(self) -> Settings:
        return self.server.settings  # type: ignore[attr-defined]

    @property
    def api_token(self) -> str:
        return self.server.api_token  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/audio":
            self._send_json(404, {"error": "not_found"})
            return

        if not self._is_authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            payload = self._read_json()
            content, media_type, headers = self._download_audio(payload)
        except ValueError as error:
            logger.warning("Audio API bad request: %s", error)
            self._send_json(400, {"error": "bad_request", "message": str(error)})
            return
        except AudioNotFoundError as error:
            logger.info("Audio API did not find playable audio: %s", error)
            self._send_json(404, {"error": "audio_not_found", "message": str(error)})
            return
        except Exception as error:
            logger.exception("Audio API download failed")
            self._send_json(500, {"error": "download_failed", "message": str(error)})
            return

        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        logger.info("audio_api %s - %s", self.address_string(), format % args)

    def _is_authorized(self) -> bool:
        if not self.api_token:
            return True
        expected = f"Bearer {self.api_token}"
        return self.headers.get("Authorization", "") == expected

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            raise ValueError("empty request body")
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object is required")
        return payload

    def _download_audio(self, payload: dict[str, Any]) -> tuple[bytes, str, dict[str, str]]:
        initial_url = _download_url(payload)
        candidate_urls = _candidate_download_urls(
            self.settings,
            payload,
            initial_url,
            platform_auth_slot=None,
        )
        if not candidate_urls:
            raise AudioNotFoundError("YouTube Music search returned no usable results")

        request_id = uuid.uuid4().hex
        errors: list[str] = []
        for index, url in enumerate(candidate_urls, start=1):
            route = _route_for_audio(payload, url)
            for slot in _youtube_slot_order(self.settings):
                slot_label = "active" if slot is None else str(slot)
                output_dir = self.settings.base_dir / "media" / "audio_api" / request_id / str(index) / slot_label

                while True:
                    proxy = get_next_proxy(self.settings)
                    proxy_url = str(proxy["proxy_url"]) if proxy else None
                    proxy_id = int(proxy["id"]) if proxy else None
                    if not proxy_url:
                        proxy_url = ""

                    try:
                        items = download_media_bundle(
                            settings=self.settings,
                            url=url,
                            route=route,
                            output_dir=output_dir,
                            quality=None,
                            audio_lang=None,
                            audio_format_id=None,
                            platform_auth_slot=slot,
                            proxy_url=proxy_url,
                        )
                        item = _pick_audio(items)
                        if item is None:
                            raise RuntimeError("download completed but no audio file was created")
                        if proxy_id is not None:
                            mark_proxy_success(self.settings, proxy_id)
                        content = item.path.read_bytes()
                        media_type = mimetypes.guess_type(item.path.name)[0] or "audio/mpeg"
                        headers = {
                            "X-Cache-Key": _cache_key(payload, url, item),
                            "X-Source-Url": url,
                            "X-Auth-Slot": slot_label,
                        }
                        if proxy_id is not None:
                            headers["X-Proxy-ID"] = str(proxy_id)
                        return content, media_type, headers
                    except Exception as error:
                        proxy_failed = proxy_id is not None and is_proxy_error(error)
                        proxy_became_dead = False
                        if proxy_id is not None:
                            proxy_became_dead = mark_proxy_failed(
                                self.settings,
                                proxy_id,
                                str(error),
                                dead=proxy_failed,
                            )
                        errors.append(f"{url} slot={slot_label}: {error}")
                        logger.warning(
                            "Audio API candidate failed | candidate=%s/%s slot=%s proxy=%s url=%s error=%s",
                            index,
                            len(candidate_urls),
                            slot_label,
                            mask_proxy(proxy_url or "") if proxy_url else "-",
                            url,
                            error,
                        )
                        if proxy_failed:
                            logger.warning("Proxy marked DEAD | id=%s proxy=%s", proxy_id, mask_proxy(proxy_url or ""))
                            if proxy_became_dead and proxy_id is not None:
                                _notify_admins_proxy_dead(self.settings, proxy_id, proxy_url or "", error)
                            shutil.rmtree(output_dir, ignore_errors=True)
                            continue
                        if len(candidate_urls) == 1 and len(_youtube_slot_order(self.settings)) == 1:
                            raise
                        break
                    finally:
                        shutil.rmtree(output_dir, ignore_errors=True)

        short_errors = "; ".join(errors[:3])
        raise AudioNotFoundError(f"no playable YouTube Music result found ({short_errors})")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Audio API client disconnected before JSON response was sent | status=%s", status)


def run_server() -> None:
    logging.basicConfig(
        level=getattr(logging, _env("AUDIO_API_LOG_LEVEL", _env("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    init_db(settings)

    host = _env("AUDIO_API_HOST", "127.0.0.1")
    port = _env_int("AUDIO_API_PORT", 8088)
    api_token = _env("AUDIO_API_TOKEN", "")

    server = ThreadingHTTPServer((host, port), AudioApiHandler)
    server.settings = settings  # type: ignore[attr-defined]
    server.api_token = api_token  # type: ignore[attr-defined]

    logger.info("Audio API listening on http://%s:%s/audio", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Audio API stopped by user")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
