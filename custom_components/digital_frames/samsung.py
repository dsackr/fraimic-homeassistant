"""Samsung EM32DX local transport (experimental FramePort driver).

Protocol reverse-engineered by the Joyous project (fayep/Joyous) and
documented in ``Samsung/samsung_serve.py`` / hub MDC code. This module is an
independent reimplementation for HA — see README Credits.

Flow:
  1. HA stages a PNG and exposes it at an unauthenticated token URL the
     panel can GET (same pattern as the phone app's :6868 content server).
  2. HA opens MDC TLS on port 1515, authenticates with the MDC PIN, and
     sends content-download command 0xC7 with that URL.
  3. Optional Wake-on-LAN when a Wi‑Fi MAC is configured.

**Untested on real hardware in this repo** — unit-tested with mocks only.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
from typing import Any

from .const import SAMSUNG_MDC_PORT

_LOGGER = logging.getLogger(__name__)

# MDC content-download (from Joyous samsung_serve.py / APK RE)
_MDC_HDR = 0xAA
_MDC_CMD_CONTENT_DOWNLOAD = 0xC7
_MDC_DEV_ID = 0x00
_MDC_SUB_CONTENT = 0x53
_MDC_DTYPE = 0x00


def mdc_content_download_packet(url: str) -> bytes:
    """Build an MDC content-download packet for *url* (max 255 UTF-8 bytes)."""
    url_bytes = url.encode("utf-8")
    if len(url_bytes) > 255:
        raise ValueError(f"MDC content URL too long ({len(url_bytes)} > 255)")
    data_len = len(url_bytes) + 3  # subCmd + dtype + urlLen
    checksum = (
        _MDC_CMD_CONTENT_DOWNLOAD
        + _MDC_DEV_ID
        + data_len
        + _MDC_SUB_CONTENT
        + _MDC_DTYPE
        + len(url_bytes)
        + sum(url_bytes)
    ) & 0xFF
    return (
        bytes(
            [
                _MDC_HDR,
                _MDC_CMD_CONTENT_DOWNLOAD,
                _MDC_DEV_ID,
                data_len,
                _MDC_SUB_CONTENT,
                _MDC_DTYPE,
                len(url_bytes),
            ]
        )
        + url_bytes
        + bytes([checksum])
    )


def wol_packet(mac: str) -> bytes:
    """Standard magic packet for *mac* (``aa:bb:…`` or bare hex)."""
    cleaned = mac.replace(":", "").replace("-", "").strip().lower()
    if len(cleaned) != 12 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError(f"Invalid MAC for WoL: {mac!r}")
    mac_bytes = bytes.fromhex(cleaned)
    return b"\xff" * 6 + mac_bytes * 16


def send_wol(mac: str, *, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send Wake-on-LAN magic packet (blocking)."""
    pkt = wol_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(pkt, (broadcast, port))


def mdc_port_open(host: str, port: int = SAMSUNG_MDC_PORT, timeout: float = 2.0) -> bool:
    """True if TCP connect to MDC port succeeds (frame likely awake)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def send_mdc_content_download(
    host: str,
    url: str,
    *,
    pin: str,
    port: int = SAMSUNG_MDC_PORT,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """TLS MDC content-download (blocking). Raises on hard failure.

    Returns a small result dict with banner/auth/response snippets for logs.
    """
    pkt = mdc_content_download_packet(url)
    pin_bytes = (pin or "000000").encode("utf-8")
    result: dict[str, Any] = {"host": host, "url": url}

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with socket.create_connection((host, port), timeout=timeout) as raw:
        raw.settimeout(timeout)
        banner = raw.recv(64)
        result["banner"] = banner.decode("utf-8", errors="replace")
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            tls.sendall(pin_bytes)
            auth = tls.recv(64)
            result["auth"] = auth.decode("utf-8", errors="replace")
            if b"MDCAUTH<<PASS>>" not in auth:
                raise ConnectionError(
                    f"Samsung MDC auth failed (check PIN): {result['auth']!r}"
                )
            tls.sendall(pkt)
            try:
                resp = tls.recv(64)
                result["response_hex"] = resp.hex()
            except socket.timeout:
                result["response_hex"] = ""
    return result
