"""PanelCodec registry & encode seam (FramePort Phase 1 / KPF 7 + 23)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.digital_frames.frame_types import (
    CODEC_SPECTRA6_SEQUENTIAL,
    CODEC_SPECTRA6_SPLIT_HALF,
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
)
from custom_components.digital_frames.panel_codec import (
    CODECS,
    CODEC_JPEG_Q90,
    encode_for_panel,
    panel_codec_for_entry,
    panel_codec_for_frame_type_id,
    panel_codec_for_id,
    panel_codec_for_resolution,
    text_skill_payload_for_codec,
)


def test_both_spectra_codecs_are_registered():
    assert CODEC_SPECTRA6_SPLIT_HALF in CODECS
    assert CODEC_SPECTRA6_SEQUENTIAL in CODECS
    assert CODECS[CODEC_SPECTRA6_SPLIT_HALF].byte_layout == LAYOUT_SPLIT_HALF
    assert CODECS[CODEC_SPECTRA6_SEQUENTIAL].byte_layout == LAYOUT_SEQUENTIAL


def test_panel_codec_for_resolution_matches_frame_types():
    for ft in FRAME_TYPES.values():
        w, h = ft.resolution
        codec = panel_codec_for_resolution(w, h)
        assert codec.id == ft.codec_id
        assert codec.byte_layout == ft.byte_layout


def test_panel_codec_for_frame_type_id():
    assert panel_codec_for_frame_type_id("7.3").id == CODEC_SPECTRA6_SEQUENTIAL
    assert panel_codec_for_frame_type_id("13.3").id == CODEC_SPECTRA6_SPLIT_HALF


def test_panel_codec_for_entry_prefers_size():
    entry = SimpleNamespace(
        entry_id="e1",
        data={"size": "7.3", "width": 1200, "height": 1600},
    )
    # size wins even if dimensions look like 13.3
    assert panel_codec_for_entry(entry).id == CODEC_SPECTRA6_SEQUENTIAL


def test_panel_codec_for_entry_falls_back_to_dimensions():
    entry = SimpleNamespace(entry_id="e1", data={"width": 800, "height": 480})
    assert panel_codec_for_entry(entry).id == CODEC_SPECTRA6_SEQUENTIAL


def test_panel_codec_for_entry_raises_without_hints():
    entry = SimpleNamespace(entry_id="e1", data={})
    with pytest.raises(ValueError, match="no size or dimensions"):
        panel_codec_for_entry(entry)


def test_unknown_codec_id_raises():
    with pytest.raises(ValueError, match="Unknown panel codec"):
        panel_codec_for_id("not_a_codec")


def test_encode_for_panel_uses_registered_resolution(sample_image_bytes):
    # Smoke: both codecs produce the expected 4bpp length.
    for ft in FRAME_TYPES.values():
        w, h = ft.resolution
        out = encode_for_panel(sample_image_bytes(200, 150), w, h)
        assert len(out) == (w * h) // 2


def test_encode_for_panel_rejects_unknown_resolution(sample_image_bytes):
    with pytest.raises(ValueError, match="No registered frame type"):
        encode_for_panel(sample_image_bytes(10, 10), 9999, 9999)


def test_text_skill_payload_spectra_pass_through_with_preview(sample_image_bytes):
    w, h = 1200, 1600
    bin_bytes = encode_for_panel(sample_image_bytes(200, 150), w, h)
    wire, preview = text_skill_payload_for_codec(
        bin_bytes, w, h, 0, CODEC_SPECTRA6_SPLIT_HALF
    )
    assert wire is bin_bytes or wire == bin_bytes
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_text_skill_payload_jpeg_from_spectra_bin_fallback(sample_image_bytes):
    # No RGB PNG: JPEG path falls back to unpacking Spectra .bin.
    w, h = 1200, 1600
    bin_bytes = encode_for_panel(sample_image_bytes(400, 300), w, h)
    wire, preview = text_skill_payload_for_codec(
        bin_bytes, w, h, 0, CODEC_JPEG_Q90, None
    )
    assert wire[:2] == b"\xff\xd8"
    assert len(wire) > 100
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_text_skill_payload_jpeg_prefers_rgb_png(sample_image_bytes):
    """Meural path encodes from full RGB preview, not Spectra unpack."""
    from PIL import Image
    import io

    w, h = 200, 100
    # Distinct non-Spectra color so unpack-fallback would not match.
    img = Image.new("RGB", (w, h), color=(12, 34, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rgb_png = buf.getvalue()
    # Invalid bin would fail if RGB path were ignored.
    wire, preview = text_skill_payload_for_codec(
        b"not-a-valid-bin", w, h, 0, CODEC_JPEG_Q90, rgb_png
    )
    assert wire[:2] == b"\xff\xd8"
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_text_skill_payload_jpeg_bad_bin_raises_without_rgb():
    with pytest.raises(ValueError, match="bin is"):
        text_skill_payload_for_codec(b"too-short", 1920, 1080, 0, CODEC_JPEG_Q90, None)


def test_text_skill_payload_spectra_bad_bin_soft_preview():
    wire, preview = text_skill_payload_for_codec(
        b"not-a-bin", 1200, 1600, 0, CODEC_SPECTRA6_SPLIT_HALF, None
    )
    assert wire == b"not-a-bin"
    assert preview is None


def test_text_skill_payload_spectra_prefers_rgb_preview(sample_image_bytes):
    w, h = 1200, 1600
    bin_bytes = encode_for_panel(sample_image_bytes(400, 300), w, h)
    rgb_png = sample_image_bytes(w, h)
    wire, preview = text_skill_payload_for_codec(
        bin_bytes, w, h, 0, CODEC_SPECTRA6_SPLIT_HALF, rgb_png
    )
    assert wire == bin_bytes
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"
