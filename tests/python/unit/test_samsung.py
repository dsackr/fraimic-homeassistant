"""Samsung EM32DX MDC driver (experimental / KPF 34)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.fraimic.const import (
    CONF_DRIVER,
    DRIVER_SAMSUNG,
    SAMSUNG_SIZE_LABEL,
)
from custom_components.fraimic.panel_codec import (
    CODEC_PNG,
    encode_for_panel,
    panel_codec_for_entry,
)
from custom_components.fraimic.samsung import (
    mdc_content_download_packet,
    wol_packet,
)


def test_panel_codec_for_samsung_entry():
    entry = SimpleNamespace(
        entry_id="s1",
        data={
            CONF_DRIVER: DRIVER_SAMSUNG,
            "width": 2560,
            "height": 1440,
            "size": SAMSUNG_SIZE_LABEL,
        },
    )
    assert panel_codec_for_entry(entry).id == CODEC_PNG
    assert panel_codec_for_entry(entry).preferred_payload == "png"


def test_encode_png_for_samsung_geometry(sample_image_bytes):
    out = encode_for_panel(
        sample_image_bytes(400, 300),
        2560,
        1440,
        0,
        False,
        "fast",
        None,
        CODEC_PNG,
    )
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(out) > 100


def test_mdc_content_download_packet_structure():
    url = "http://192.168.1.10:8123/api/fraimic/samsung/tok/content.png"
    pkt = mdc_content_download_packet(url)
    assert pkt[0] == 0xAA
    assert pkt[1] == 0xC7
    assert pkt[2] == 0x00
    url_bytes = url.encode("utf-8")
    assert pkt[3] == len(url_bytes) + 3
    assert pkt[4] == 0x53
    assert pkt[6] == len(url_bytes)
    assert pkt[7 : 7 + len(url_bytes)] == url_bytes
    # Checksum is last byte
    body_sum = sum(pkt[1:-1]) & 0xFF
    assert pkt[-1] == body_sum


def test_mdc_url_too_long_raises():
    with pytest.raises(ValueError, match="too long"):
        mdc_content_download_packet("http://x/" + ("a" * 300))


def test_wol_packet_length():
    pkt = wol_packet("b0:f2:f6:57:d5:cd")
    assert len(pkt) == 6 + 16 * 6
    assert pkt[:6] == b"\xff" * 6


def test_samsung_coordinator_stages_content():
    from custom_components.fraimic.samsung_coordinator import SamsungCoordinator

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "sam1"
    entry.data = {
        "host": "192.168.1.50",
        "mdc_pin": "123456",
        "mac_address": "",
    }
    entry.options = {}
    coord = SamsungCoordinator(hass, entry)
    token = coord.stage_content(b"\x89PNG fake")
    assert coord.get_staged_content(token) == b"\x89PNG fake"
    assert coord.get_staged_content("wrong") is None
