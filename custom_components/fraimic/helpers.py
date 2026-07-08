"""Shared helpers: frame render-spec resolution plus network probing/scanning."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

from .const import (
    API_INFO,
    CONF_DEVICE_KEY,
    CONF_HEIGHT,
    CONF_HOST,
    CONF_MAC,
    CONF_ORIENTATION,
    CONF_ROTATE_LANDSCAPE_180,
    CONF_ROTATE_PORTRAIT_180,
    CONF_ROTATION_EDGE,
    CONF_WIDTH,
    EDGE_LEFT,
    ORIENTATION_AUTO,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from .frame_types import FRAME_TYPES, ORIGIN_OFFICIAL

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Render spec: the single source of truth for "how does an image get
# composed for this frame". Every send path (service call, direct upload,
# library send, scenes, backfill) resolves a frame's config entry through
# render_spec() instead of reading entry.data width/height directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderSpec:
    """How to compose + rotate an image for one frame.

    width/height are the *effective* composition dimensions (what the crop
    editor's aspect ratio and the cover-crop math use). rotation is the final
    canvas rotation (degrees CCW, 0/90/180/270) applied after composition to
    land back on the panel's native buffer orientation. locked is True when
    the user pinned an orientation -- mismatched images are then auto-cropped
    upright instead of displayed sideways.
    """

    width: int
    height: int
    rotation: int
    locked: bool

    @property
    def variant(self) -> str:
        """Cache-key suffix distinguishing renders that share a resolution
        but differ in rotation or locked-crop behaviour. Empty string is the
        pre-existing default render (keeps old cached .bin files valid)."""
        parts = ""
        if self.rotation:
            parts += f"_r{self.rotation}"
        if self.locked:
            parts += "_c"
        return parts


def render_spec_for_entry(entry: "ConfigEntry") -> RenderSpec:
    """Resolve a frame config entry to its RenderSpec.

    entry.data's width/height always hold the panel's native (frame-reported)
    dimensions. The orientation lock and 180-degree flips live in
    entry.options and are applied here, at render time.
    """
    native_w: int = entry.data[CONF_WIDTH]
    native_h: int = entry.data[CONF_HEIGHT]

    orientation: str = entry.options.get(CONF_ORIENTATION, ORIENTATION_AUTO)
    edge: str = entry.options.get(CONF_ROTATION_EDGE, EDGE_LEFT)

    eff_w, eff_h = native_w, native_h
    rotation = 0
    locked = orientation in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE)

    if locked:
        want_portrait = orientation == ORIENTATION_PORTRAIT
        native_portrait = native_h >= native_w
        if want_portrait != native_portrait:
            # Compose in the locked orientation, then rotate the finished
            # canvas back onto the native buffer. "Left edge up" (the frame's
            # native-left edge physically on top, i.e. the frame was turned
            # clockwise -- how official Fraimic frames hang) needs a 90-degree
            # CCW canvas rotation so composed-top lands on native-left;
            # "right edge up" needs 270. If images come out upside down on a
            # clone, the edge option is the thing to flip.
            eff_w, eff_h = native_h, native_w
            rotation = 90 if edge == EDGE_LEFT else 270

    # 180-degree flip is keyed off the *effective* orientation the viewer
    # sees, and composes with any lock rotation above.
    eff_is_landscape = eff_w > eff_h
    if eff_is_landscape and entry.options.get(CONF_ROTATE_LANDSCAPE_180):
        rotation = (rotation + 180) % 360
    elif not eff_is_landscape and entry.options.get(CONF_ROTATE_PORTRAIT_180):
        rotation = (rotation + 180) % 360

    return RenderSpec(width=eff_w, height=eff_h, rotation=rotation, locked=locked)

_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_SCAN_TIMEOUT = aiohttp.ClientTimeout(total=0.5)

# /info's "Device Type" row looks like:
#   <span class='info-label'>Device Type</span><span class='info-value'>13.3" E-Ink</span>
_DEVICE_TYPE_RE = re.compile(
    r"Device\s*Type\s*</span>\s*<span[^>]*>\s*([^<]*?)\s*</span>",
    re.IGNORECASE,
)
_SIZE_INCHES_RE = re.compile(r'([\d.]+)\s*"')


async def probe_frame(
    session: aiohttp.ClientSession,
    host: str,
    timeout: aiohttp.ClientTimeout | None = None,
) -> dict[str, Any] | None:
    """GET /api/info on *host*. Returns parsed JSON or None on any failure."""
    url = f"http://{host}{API_INFO}"
    try:
        async with session.get(url, timeout=timeout or _PROBE_TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        pass
    return None


async def probe_device_size(
    session: aiohttp.ClientSession, host: str
) -> str | None:
    """Best-effort auto-detect of a frame's physical size, scraped from its
    /info admin page's "Device Type" field (e.g. '13.3" E-Ink' -> "13.3").

    /api/info -- the JSON endpoint the rest of this integration relies on --
    doesn't expose size or resolution at all (confirmed against real
    hardware, not just undocumented). /info is a separate, human-facing
    HTML page with no stability guarantee, so any request failure or
    unexpected markup here just means "couldn't detect" -- config_flow
    falls back to asking the user for size instead of raising.
    """
    try:
        async with session.get(f"http://{host}/info", timeout=_PROBE_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
    except Exception:  # noqa: BLE001
        return None

    match = _DEVICE_TYPE_RE.search(html)
    if not match:
        return None
    inches_match = _SIZE_INCHES_RE.search(match.group(1))
    if not inches_match:
        return None
    size = inches_match.group(1)
    return size if size in FRAME_TYPES else None


def get_local_ip() -> str:
    """Return the IPv4 address of the HA machine, falling back to 192.168.1.1.

    A UDP connect() does no I/O, but it's still a syscall that can block
    (routing lookups) -- callers must run this via
    hass.async_add_executor_job, never directly on the event loop.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "192.168.1.1"


def device_key_from_info(info: dict[str, Any]) -> str | None:
    """Extract the persistent device_key from a /api/info response."""
    return info.get("device", {}).get("device_key") or None


def mac_from_info(info: dict[str, Any]) -> str:
    """Extract the normalised (no colons, lowercase) MAC from a /api/info response."""
    raw = info.get("wifi", {}).get("mac", "")
    return raw.replace(":", "").lower()


# Official Fraimic Wi-Fi module OUIs. Mirrors manifest.json's dhcp
# matchers (which can't be imported from here) -- keep the two in sync.
_OFFICIAL_MAC_PREFIXES = ("1cdbd4", "3cdc75")


def detect_frame_type_from_info(info: dict[str, Any]) -> str | None:
    """Infer the frame type from /api/info's reported pixel dimensions.

    Second-line detection behind probe_device_size's /info HTML scrape:
    clones' community firmware doesn't serve that page in the expected
    format, but every firmware that reports width/height in /api/info can
    be matched against the frame-type registry by resolution
    (orientation-agnostic, like byte_layout_for_resolution).

    Resolutions shared by multiple types (13.3" official vs 13.1" clone,
    both 1200x1600) are disambiguated by MAC OUI -- functionally either
    answer renders identically (the registry validates shared resolutions
    agree on byte layout), so this only affects the display label.
    """
    width = info.get("width")
    height = info.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        return None

    candidates = [
        ft for ft in FRAME_TYPES.values()
        if ft.resolution in ((width, height), (height, width))
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].id

    is_official = mac_from_info(info).startswith(_OFFICIAL_MAC_PREFIXES)
    for frame_type in candidates:
        if (frame_type.origin == ORIGIN_OFFICIAL) == is_official:
            return frame_type.id
    return candidates[0].id


def match_and_update_entry(
    hass: "HomeAssistant",
    entries: list["ConfigEntry"],
    ip: str,
    info: dict[str, Any],
) -> "ConfigEntry | None":
    """Return the configured entry for the frame probed at *ip*, or None.

    Single source of truth for "is this the same physical frame" — shared by
    DHCP discovery and the periodic background scan so the matching rules can
    never drift. Matches on device_key (new entries), MAC (belt-and-braces),
    or — for entries created before 0.4.1 that don't have a device_key/MAC
    yet (only backfilled lazily on the frame's next successful coordinator
    poll) — falls back to matching on the entry's currently configured host.
    Without this fallback, a probe arriving before that first poll completes
    (e.g. right after upgrading and restarting) would fail to match an
    existing entry and create a duplicate for an already-configured frame.

    On a match, the entry's host is updated if the frame moved, and the
    device_key/MAC fingerprint is backfilled if this was a legacy entry.
    """
    key = device_key_from_info(info)
    mac = mac_from_info(info)

    for entry in entries:
        entry_key = entry.data.get(CONF_DEVICE_KEY)
        entry_mac = entry.data.get(CONF_MAC, "")
        entry_host = entry.data.get(CONF_HOST)
        is_same_frame = (
            (entry_key and entry_key == key)
            or (mac and entry_mac and entry_mac == mac)
            or (not entry_key and not entry_mac and entry_host == ip)
        )
        if not is_same_frame:
            continue
        if entry_host != ip or not entry_key or not entry_mac:
            _LOGGER.info(
                "Fraimic frame %s moved: %s → %s", key, entry_host, ip
            )
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_HOST: ip,
                    CONF_DEVICE_KEY: key,
                    CONF_MAC: mac,
                },
            )
        return entry
    return None


async def scan_subnet(
    host_ip: str,
    session: aiohttp.ClientSession,
    *,
    concurrency: int = 64,
) -> list[dict[str, Any]]:
    """Probe all 254 host addresses in the /24 subnet of *host_ip*.

    Uses the caller's *session* (pass HA's managed session via
    async_get_clientsession). Probes are bounded by *concurrency*: firing all
    254 at once through a shared connector can exceed its connection limit,
    and a probe stuck waiting in the connector queue burns its 0.5 s total
    timeout before a single packet is sent -- silently missing live frames.
    The semaphore is acquired *before* the request starts, so the timeout
    only ever covers actual network time. Worst case a full sweep takes
    ~254/concurrency * 0.5 s (~2 s at the default).

    Returns a list of ``{"ip": str, "info": dict}`` for every address that
    responded as a Fraimic frame (i.e. returned a valid /api/info payload with
    a device_key).
    """
    try:
        network = ipaddress.IPv4Network(f"{host_ip}/24", strict=False)
    except ValueError:
        return []

    hosts = [str(h) for h in network.hosts()]
    semaphore = asyncio.Semaphore(concurrency)

    async def _probe_bounded(host: str) -> dict[str, Any] | None:
        async with semaphore:
            return await probe_frame(session, host, _SCAN_TIMEOUT)

    results = await asyncio.gather(
        *(_probe_bounded(h) for h in hosts), return_exceptions=True
    )

    found: list[dict[str, Any]] = []
    for addr, result in zip(hosts, results):
        if isinstance(result, dict) and device_key_from_info(result):
            found.append({"ip": addr, "info": result})
    return found


async def find_frame_by_device_key(
    host_ip: str, device_key: str, session: aiohttp.ClientSession
) -> str | None:
    """Scan the /24 subnet and return the IP of the frame with *device_key*, or None."""
    results = await scan_subnet(host_ip, session)
    for entry in results:
        if device_key_from_info(entry["info"]) == device_key:
            return entry["ip"]
    return None
