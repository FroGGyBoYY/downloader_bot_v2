from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import urlopen

from app.config import Settings
from app.db.cookie_auth_repo import log_admin_action
from app.db.database import db_connect


PROXY_SERVICE = "youtube_music"
ACTIVE = "ACTIVE"
DEAD = "DEAD"
UNKNOWN_COUNTRY = "??"
_COUNTRY_CACHE: dict[str, tuple[str, str]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_proxy_line(line: str) -> str | None:
    value = str(line or "").strip()
    if not value or value.startswith("#"):
        return None

    value = value.strip(" ,;")
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "socks4", "socks5"}:
            return None
        if not parsed.hostname or not parsed.port:
            return None
        return value

    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts
        if host and port.isdigit():
            return f"http://{host}:{port}"
    if len(parts) >= 4:
        host = parts[0].strip()
        port = parts[1].strip()
        username = parts[2].strip()
        password = ":".join(parts[3:]).strip()
        if host and port.isdigit() and username and password:
            return f"http://{username}:{password}@{host}:{port}"

    return None


def parse_proxy_payload(text: str) -> list[str]:
    proxies: list[str] = []
    seen: set[str] = set()
    for raw_line in re.split(r"[\r\n]+", str(text or "")):
        for raw in re.split(r"[\s,;]+", raw_line.strip()):
            proxy = normalize_proxy_line(raw)
            if proxy and proxy not in seen:
                seen.add(proxy)
                proxies.append(proxy)
    return proxies


def add_proxies(settings: Settings, proxies: list[str], *, admin_id: int | None = None) -> tuple[int, int]:
    current = now_iso()
    added = 0
    reactivated = 0
    conn = db_connect(settings)
    for raw_proxy_url in proxies:
        proxy_url = normalize_proxy_line(raw_proxy_url)
        if not proxy_url:
            continue
        country_code, country_name = lookup_proxy_country(proxy_url)
        row = conn.execute("SELECT * FROM proxy_pool WHERE proxy_url = ?", (proxy_url,)).fetchone()
        if row:
            updates: list[str] = []
            values: list[object] = []
            if str(row["status"]) != ACTIVE:
                updates.extend(["status=?", "dead_at=NULL", "last_error=NULL"])
                values.append(ACTIVE)
                reactivated += 1
            if country_code and not str(row["country_code"] or "").strip():
                updates.append("country_code=?")
                values.append(country_code)
            if country_name and not str(row["country_name"] or "").strip():
                updates.append("country_name=?")
                values.append(country_name)
            if updates:
                updates.append("updated_at=?")
                values.extend([current, proxy_url])
                conn.execute(
                    f"UPDATE proxy_pool SET {', '.join(updates)} WHERE proxy_url=?",
                    tuple(values),
                )
            continue

        conn.execute(
            """
            INSERT INTO proxy_pool (
                service, proxy_url, country_code, country_name, status, requests_count, success_count, fail_count,
                added_by, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """,
            (PROXY_SERVICE, proxy_url, country_code, country_name, ACTIVE, admin_id, current, current),
        )
        added += 1
    conn.commit()
    conn.close()
    if added or reactivated:
        log_admin_action(
            settings,
            admin_id=admin_id,
            action="proxy_add",
            target=PROXY_SERVICE,
            details=f"added={added} reactivated={reactivated}",
        )
    return added, reactivated


def get_next_proxy(settings: Settings, service: str = PROXY_SERVICE) -> dict | None:
    conn = db_connect(settings)
    row = conn.execute(
        """
        SELECT *
        FROM proxy_pool
        WHERE service=? AND status=?
        ORDER BY id ASC
        LIMIT 1
        """,
        (service, ACTIVE),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_proxy_by_id(settings: Settings, proxy_id: int) -> dict | None:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT * FROM proxy_pool WHERE id=? AND service=?",
        (proxy_id, PROXY_SERVICE),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_proxy_by_id(
    settings: Settings,
    proxy_id: int,
    *,
    admin_id: int | None = None,
) -> dict | None:
    row = get_proxy_by_id(settings, proxy_id)
    if not row:
        return None

    conn = db_connect(settings)
    conn.execute(
        "DELETE FROM proxy_pool WHERE id=? AND service=?",
        (proxy_id, PROXY_SERVICE),
    )
    conn.commit()
    conn.close()
    log_admin_action(
        settings,
        admin_id=admin_id,
        action="proxy_delete_one",
        target=PROXY_SERVICE,
        details=f"id={proxy_id} proxy={mask_proxy(str(row.get('proxy_url') or ''))}",
    )
    return row


def delete_all_proxies(settings: Settings, *, admin_id: int | None = None) -> int:
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM proxy_pool WHERE service=?",
        (PROXY_SERVICE,),
    ).fetchone()
    count = int(row["count"] or 0) if row else 0
    conn.execute("DELETE FROM proxy_pool WHERE service=?", (PROXY_SERVICE,))
    conn.commit()
    conn.close()
    if count:
        log_admin_action(
            settings,
            admin_id=admin_id,
            action="proxy_delete_all",
            target=PROXY_SERVICE,
            details=f"count={count}",
        )
    return count


def mark_proxy_success(settings: Settings, proxy_id: int) -> None:
    current = now_iso()
    conn = db_connect(settings)
    conn.execute(
        """
        UPDATE proxy_pool
        SET requests_count=requests_count + 1,
            success_count=success_count + 1,
            first_used_at=COALESCE(first_used_at, ?),
            last_used_at=?,
            updated_at=?
        WHERE id=?
        """,
        (current, current, current, proxy_id),
    )
    conn.commit()
    conn.close()


def mark_proxy_failed(settings: Settings, proxy_id: int, error: str, *, dead: bool) -> bool:
    current = now_iso()
    status = DEAD if dead else ACTIVE
    conn = db_connect(settings)
    row = conn.execute(
        "SELECT status FROM proxy_pool WHERE id=?",
        (proxy_id,),
    ).fetchone()
    was_dead = bool(row and str(row["status"]) == DEAD)
    conn.execute(
        """
        UPDATE proxy_pool
        SET requests_count=requests_count + 1,
            fail_count=fail_count + 1,
            status=?,
            first_used_at=COALESCE(first_used_at, ?),
            last_used_at=?,
            dead_at=CASE WHEN ? THEN ? ELSE dead_at END,
            last_error=?,
            updated_at=?
        WHERE id=?
        """,
        (status, current, current, int(dead), current, str(error)[:500], current, proxy_id),
    )
    conn.commit()
    conn.close()
    return bool(dead and not was_dead)


def list_proxies(settings: Settings, *, include_dead: bool = False) -> list[dict]:
    conn = db_connect(settings)
    if include_dead:
        rows = conn.execute(
            "SELECT * FROM proxy_pool WHERE service=? ORDER BY status ASC, id ASC",
            (PROXY_SERVICE,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM proxy_pool WHERE service=? AND status=? ORDER BY id ASC",
            (PROXY_SERVICE, ACTIVE),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def proxy_counts(settings: Settings) -> dict[str, int]:
    conn = db_connect(settings)
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM proxy_pool WHERE service=? GROUP BY status",
        (PROXY_SERVICE,),
    ).fetchall()
    conn.close()
    result = {"active": 0, "dead": 0, "total": 0}
    for row in rows:
        status = str(row["status"]).lower()
        count = int(row["count"] or 0)
        result[status] = count
        result["total"] += count
    return result


def proxy_stats(settings: Settings) -> dict[str, float | int]:
    rows = list_proxies(settings, include_dead=True)
    counts = proxy_counts(settings)
    dead_rows = [row for row in rows if row.get("status") == DEAD]
    lifetime_rows = dead_rows or rows
    request_values = [int(row.get("requests_count") or 0) for row in lifetime_rows]
    day_values = [_lifetime_days(row) for row in lifetime_rows]
    return {
        **counts,
        "avg_requests": round(sum(request_values) / len(request_values), 2) if request_values else 0,
        "avg_days": round(sum(day_values) / len(day_values), 2) if day_values else 0,
        "success": sum(int(row.get("success_count") or 0) for row in rows),
        "fail": sum(int(row.get("fail_count") or 0) for row in rows),
    }


def backfill_proxy_countries(settings: Settings, *, limit: int = 80) -> int:
    conn = db_connect(settings)
    rows = conn.execute(
        """
        SELECT id, proxy_url
        FROM proxy_pool
        WHERE service=?
          AND (country_code IS NULL OR country_code = '')
        ORDER BY id ASC
        LIMIT ?
        """,
        (PROXY_SERVICE, limit),
    ).fetchall()
    updated = 0
    current = now_iso()
    for row in rows:
        country_code, country_name = lookup_proxy_country(str(row["proxy_url"]))
        if not country_code:
            continue
        conn.execute(
            """
            UPDATE proxy_pool
            SET country_code=?, country_name=?, updated_at=?
            WHERE id=?
            """,
            (country_code, country_name, current, int(row["id"])),
        )
        updated += 1
    conn.commit()
    conn.close()
    return updated


def proxy_health_stats(settings: Settings) -> list[dict[str, object]]:
    rows = list_proxies(settings, include_dead=True)
    groups: dict[str, dict[str, object]] = {}
    for row in rows:
        country_code = str(row.get("country_code") or UNKNOWN_COUNTRY).upper()
        country_name = str(row.get("country_name") or "").strip()
        label = country_code if not country_name else f"{country_code} {country_name}"
        group = groups.setdefault(
            country_code,
            {
                "country_code": country_code,
                "country_name": country_name,
                "label": label,
                "total": 0,
                "active": 0,
                "dead": 0,
                "success": 0,
                "fail": 0,
                "requests": 0,
                "life_days": [],
                "dead_life_days": [],
                "active_age_days": [],
                "last_dead": None,
            },
        )
        group["total"] = int(group["total"]) + 1
        requests = int(row.get("requests_count") or 0)
        group["requests"] = int(group["requests"]) + requests
        group["success"] = int(group["success"]) + int(row.get("success_count") or 0)
        group["fail"] = int(group["fail"]) + int(row.get("fail_count") or 0)
        life_days = _lifetime_days_to_now_or_dead(row)
        group["life_days"].append(life_days)  # type: ignore[union-attr]
        if row.get("status") == DEAD:
            group["dead"] = int(group["dead"]) + 1
            group["dead_life_days"].append(life_days)  # type: ignore[union-attr]
            last_dead = group.get("last_dead")
            if not last_dead or str(row.get("dead_at") or "") > str(last_dead.get("dead_at") or ""):  # type: ignore[union-attr]
                group["last_dead"] = row
        else:
            group["active"] = int(group["active"]) + 1
            group["active_age_days"].append(life_days)  # type: ignore[union-attr]

    result: list[dict[str, object]] = []
    for group in groups.values():
        total = int(group["total"])
        requests = int(group["requests"])
        life_values = list(group["life_days"])  # type: ignore[arg-type]
        dead_life_values = list(group["dead_life_days"])  # type: ignore[arg-type]
        active_age_values = list(group["active_age_days"])  # type: ignore[arg-type]
        result.append(
            {
                **group,
                "avg_requests": round(requests / total, 2) if total else 0,
                "avg_life_days": _avg(life_values),
                "avg_dead_life_days": _avg(dead_life_values),
                "avg_active_age_days": _avg(active_age_values),
            }
        )
    return sorted(result, key=lambda item: (-int(item["total"]), str(item["country_code"])))


def mask_proxy(proxy_url: str) -> str:
    parsed = urlparse(proxy_url)
    if parsed.username and parsed.password and parsed.hostname and parsed.port:
        return f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}"
    return proxy_url


def is_proxy_error(error: object) -> bool:
    text = str(error or "").casefold()
    markers = (
        "unable to connect to proxy",
        "proxyerror",
        "tunnel connection failed",
        "payment required",
        "407 proxy",
        "proxy authentication",
        "connection to 38.",
        "connection to 64.",
        "connection to 198.",
        "timed out",
    )
    return any(marker in text for marker in markers)


def lookup_proxy_country(proxy_url: str) -> tuple[str, str]:
    host = urlparse(proxy_url).hostname or ""
    if not host:
        return "", ""
    if host in _COUNTRY_CACHE:
        return _COUNTRY_CACHE[host]

    result = ("", "")
    try:
        with urlopen(
            f"http://ip-api.com/json/{host}?fields=status,country,countryCode",
            timeout=4,
        ) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict) and payload.get("status") == "success":
            code = str(payload.get("countryCode") or "").strip().upper()[:2]
            name = str(payload.get("country") or "").strip()[:80]
            result = (code, name)
    except Exception:
        result = ("", "")
    _COUNTRY_CACHE[host] = result
    return result


def _lifetime_days(row: dict) -> float:
    start = _parse_dt(row.get("first_used_at") or row.get("created_at"))
    end = _parse_dt(row.get("dead_at") or row.get("last_used_at")) or datetime.now(timezone.utc)
    if not start:
        return 0
    return max(0, (end - start).total_seconds() / 86400)


def _lifetime_days_to_now_or_dead(row: dict) -> float:
    start = _parse_dt(row.get("first_used_at") or row.get("created_at"))
    end = _parse_dt(row.get("dead_at")) or datetime.now(timezone.utc)
    if not start:
        return 0
    return max(0, (end - start).total_seconds() / 86400)


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
