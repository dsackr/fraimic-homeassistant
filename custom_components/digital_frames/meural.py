"""Local Meural Canvas transport (FramePort Phase 3).

Talks to a Meural on the LAN only — no Meural cloud / Cognito auth.

**Acknowledgements:** Local HTTP endpoint paths and protocol shapes for the
Canvas ``/remote/`` API were documented by the community Home Assistant
integration **HA-meural** by Guy Sie ([GuySie/ha-meural](https://github.com/GuySie/ha-meural),
MIT License). This module is an independent reimplementation for Fraimic's
FramePort driver; it does not vendor HA-meural source. See also the root
``README.md`` Credits section.

Live probes against Canvas firmware 2.3.x refined field names (e.g. gsensor,
backlight, lux) used in the coordinator.

Endpoints used (relative to http://{host}/remote/):

- GET  identify/                       — device identity probe
- GET  control_check/system/           — system info (lux, backlight, wifi, …)
- GET  control_check/sleep/            — display suspended?
- GET  get_backlight/                  — backlight level 0–100
- GET  control_command/set_backlight/{n}
- GET  control_command/suspend|resume
- GET  control_command/set_orientation/{portrait|landscape}
- POST postcard                        — multipart form field ``photo``
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=8)
_CMD_TIMEOUT = aiohttp.ClientTimeout(total=15)
_SEND_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Values reported by identify / control_check/system (gsensor).
_MEURAL_ORIENTATIONS = frozenset({"portrait", "landscape"})


def meural_orientation_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Extract portrait/landscape from a Meural identify or system dict.

    Prefer ``gsensor`` (physical hang) over ``orientation`` (UI lock) when
    both are present — they can disagree after a forced set_orientation.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("gsensor", "orientation"):
        raw = payload.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip().lower()
        if value in _MEURAL_ORIENTATIONS:
            return value
    return None


def parse_meural_system_stats(system: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten useful local fields from control_check/system response."""
    out: dict[str, Any] = {
        "backlight": None,
        "lux": None,
        "free_space_mb": None,
        "wifi_rssi": None,
        "wifi_ssid": None,
    }
    if not isinstance(system, dict):
        return out

    raw_bl = system.get("backlight")
    try:
        if raw_bl is not None and str(raw_bl).strip() != "":
            bl = int(float(str(raw_bl).strip()))
            out["backlight"] = max(0, min(100, bl))
    except (TypeError, ValueError):
        pass

    raw_lux = system.get("lux")
    try:
        if raw_lux is not None and str(raw_lux).strip() != "":
            out["lux"] = float(str(raw_lux).strip())
    except (TypeError, ValueError):
        pass

    raw_free = system.get("free_space")
    try:
        if raw_free is not None:
            out["free_space_mb"] = int(float(raw_free))
    except (TypeError, ValueError):
        pass

    wifi = system.get("wifi_status")
    if isinstance(wifi, dict):
        if wifi.get("name"):
            out["wifi_ssid"] = str(wifi["name"])
        # Observed as dBm-like string e.g. "-53"
        raw_sig = wifi.get("signal")
        try:
            if raw_sig is not None and str(raw_sig).strip() != "":
                out["wifi_rssi"] = int(float(str(raw_sig).strip()))
        except (TypeError, ValueError):
            pass

    return out


def _remote_url(host: str, path: str) -> str:
    path = path.lstrip("/")
    return f"http://{host}/remote/{path}"


async def _get_json(
    session: aiohttp.ClientSession,
    host: str,
    path: str,
    *,
    timeout: aiohttp.ClientTimeout = _PROBE_TIMEOUT,
) -> Any | None:
    """GET a remote path; return parsed JSON or None on transport/parse errors."""
    try:
        async with session.get(_remote_url(host, path), timeout=timeout) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        _LOGGER.debug("Meural GET %s %s failed: %s", host, path, err)
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "response" in payload:
        return payload["response"]
    return payload


def _status_ok(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    return status is None or status == "pass"


async def probe_meural(
    session: aiohttp.ClientSession, host: str
) -> dict[str, Any] | None:
    """Return identify payload if *host* looks like a local Meural, else None."""
    host = host.strip()
    if not host:
        return None
    payload = await _get_json(session, host, "identify/")
    if not isinstance(payload, dict):
        return None
    if payload.get("status") == "fail":
        return None
    inner = payload.get("response", payload)
    if not isinstance(inner, dict):
        return {"raw": payload, "host": host}
    return {**inner, "host": host}


async def meural_system_info(
    session: aiohttp.ClientSession, host: str
) -> dict[str, Any] | None:
    """Best-effort system check; None on any failure."""
    payload = await _get_json(session, host, "control_check/system/")
    if not isinstance(payload, dict):
        return None
    inner = payload.get("response", payload)
    return inner if isinstance(inner, dict) else payload


async def meural_is_sleeping(
    session: aiohttp.ClientSession, host: str
) -> bool | None:
    """True if display is suspended, False if awake, None if unknown."""
    payload = await _get_json(session, host, "control_check/sleep/")
    if not isinstance(payload, dict) or not _status_ok(payload):
        return None
    resp = payload.get("response")
    if isinstance(resp, bool):
        return resp
    if resp in ("true", "True", 1, "1"):
        return True
    if resp in ("false", "False", 0, "0"):
        return False
    return None


async def meural_get_backlight(
    session: aiohttp.ClientSession, host: str
) -> int | None:
    """Backlight level 0–100, or None."""
    payload = await _get_json(session, host, "get_backlight/")
    if not isinstance(payload, dict) or not _status_ok(payload):
        return None
    raw = payload.get("response")
    try:
        return max(0, min(100, int(float(str(raw).strip()))))
    except (TypeError, ValueError):
        return None


async def meural_set_backlight(
    session: aiohttp.ClientSession, host: str, level: int
) -> None:
    """Set backlight 0–100. Raises on hard failure."""
    level = max(0, min(100, int(level)))
    payload = await _get_json(
        session,
        host,
        f"control_command/set_backlight/{level}",
        timeout=_CMD_TIMEOUT,
    )
    if payload is None:
        raise aiohttp.ClientError(f"Meural set_backlight/{level} failed")
    if isinstance(payload, dict) and payload.get("status") == "fail":
        raise ValueError(f"Meural set_backlight rejected: {payload.get('response')!r}")


async def meural_suspend(session: aiohttp.ClientSession, host: str) -> None:
    payload = await _get_json(
        session, host, "control_command/suspend", timeout=_CMD_TIMEOUT
    )
    if payload is None:
        raise aiohttp.ClientError("Meural suspend failed")
    if isinstance(payload, dict) and payload.get("status") == "fail":
        raise ValueError(f"Meural suspend rejected: {payload.get('response')!r}")


async def meural_resume(session: aiohttp.ClientSession, host: str) -> None:
    payload = await _get_json(
        session, host, "control_command/resume", timeout=_CMD_TIMEOUT
    )
    if payload is None:
        raise aiohttp.ClientError("Meural resume failed")
    if isinstance(payload, dict) and payload.get("status") == "fail":
        raise ValueError(f"Meural resume rejected: {payload.get('response')!r}")


async def meural_set_orientation(
    session: aiohttp.ClientSession, host: str, orientation: str
) -> None:
    """Force Canvas UI orientation (portrait|landscape)."""
    orientation = orientation.strip().lower()
    if orientation not in _MEURAL_ORIENTATIONS:
        raise ValueError(f"Invalid Meural orientation: {orientation!r}")
    payload = await _get_json(
        session,
        host,
        f"control_command/set_orientation/{orientation}",
        timeout=_CMD_TIMEOUT,
    )
    if payload is None:
        raise aiohttp.ClientError(f"Meural set_orientation/{orientation} failed")
    if isinstance(payload, dict) and payload.get("status") == "fail":
        raise ValueError(
            f"Meural set_orientation rejected: {payload.get('response')!r}"
        )


async def send_meural_postcard(
    session: aiohttp.ClientSession,
    host: str,
    image_bytes: bytes,
    *,
    content_type: str = "image/jpeg",
) -> dict[str, Any]:
    """POST *image_bytes* as a postcard to the Meural at *host*.

    Returns a small result dict. Raises aiohttp.ClientError / TimeoutError /
    ValueError on hard failure.
    """
    if content_type == "image/jpg":
        content_type = "image/jpeg"

    form = aiohttp.FormData()
    form.add_field(
        "photo",
        image_bytes,
        filename="fraimic.jpg",
        content_type=content_type,
    )
    url = _remote_url(host, "postcard")
    async with session.post(url, data=form, timeout=_SEND_TIMEOUT) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise aiohttp.ClientResponseError(
                resp.request_info,
                resp.history,
                status=resp.status,
                message=text[:200],
                headers=resp.headers,
            )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"Meural postcard non-JSON response: {text[:200]}") from err

    status = payload.get("status") if isinstance(payload, dict) else None
    if status and status != "pass":
        raise ValueError(
            f"Meural postcard rejected: {payload.get('response', payload)!r}"
        )
    return payload if isinstance(payload, dict) else {"raw": payload}
