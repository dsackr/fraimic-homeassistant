"""Local Meural Canvas transport (FramePort Phase 3).

Talks to a Meural on the LAN only — no Meural cloud / Cognito auth. Protocol
knowledge is drawn from the community HA-meural integration (GuySie/ha-meural
LocalMeural client): postcard image upload and identify/system probes.

Endpoints used (relative to http://{host}/remote/):

- GET  identify/              — device identity probe
- GET  control_check/system/  — optional system info
- POST postcard               — multipart form field ``photo`` = image bytes
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=8)
_SEND_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Values reported by identify / control_check/system (gsensor).
_MEURAL_ORIENTATIONS = frozenset({"portrait", "landscape"})


def meural_orientation_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Extract portrait/landscape from a Meural identify or system dict.

    Observed keys (firmware 2.3.x): ``orientation`` and ``gsensor`` both set
    to ``\"portrait\"`` or ``\"landscape\"``. Returns None when unknown.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("orientation", "gsensor"):
        raw = payload.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip().lower()
        if value in _MEURAL_ORIENTATIONS:
            return value
    return None


def _remote_url(host: str, path: str) -> str:
    path = path.lstrip("/")
    return f"http://{host}/remote/{path}"


async def probe_meural(
    session: aiohttp.ClientSession, host: str
) -> dict[str, Any] | None:
    """Return identify payload if *host* looks like a local Meural, else None."""
    host = host.strip()
    if not host:
        return None
    try:
        async with session.get(
            _remote_url(host, "identify/"), timeout=_PROBE_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            # Meural sometimes omits Content-Type; parse leniently.
            text = await resp.text()
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        _LOGGER.debug("Meural probe %s failed: %s", host, err)
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    # Observed shapes: {"status":"pass","response":{...}} or bare object.
    if not isinstance(payload, dict):
        return None
    if payload.get("status") == "fail":
        return None
    inner = payload.get("response", payload)
    if not isinstance(inner, dict):
        # Even an empty pass is enough to treat as Meural-shaped.
        return {"raw": payload, "host": host}
    return {**inner, "host": host}


async def meural_system_info(
    session: aiohttp.ClientSession, host: str
) -> dict[str, Any] | None:
    """Best-effort system check; None on any failure."""
    try:
        async with session.get(
            _remote_url(host, "control_check/system/"), timeout=_PROBE_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
        payload = json.loads(text)
        if isinstance(payload, dict):
            inner = payload.get("response", payload)
            return inner if isinstance(inner, dict) else payload
    except (aiohttp.ClientError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return None


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
