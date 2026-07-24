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
    CODEC_PNG,
    encode_for_panel,
    encode_for_panel_with_preview,
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


def test_encode_for_panel_with_preview_spectra_crop_box_matches_encode_for_panel(
    sample_image_bytes,
):
    """A wall-banner message's per-frame slice must produce identical wire
    bytes whether requested via encode_for_panel or the _with_preview
    variant -- the preview path must not silently diverge from what's
    actually sent."""
    w, h = 1200, 1600
    source = sample_image_bytes(400, 300, color=(200, 50, 50))
    crop_box = (0.1, 0.1, 0.6, 0.9)

    wire_only = encode_for_panel(source, w, h, crop_box=crop_box)
    wire, preview = encode_for_panel_with_preview(
        source, w, h, codec_id=None, crop_box=crop_box
    )

    assert wire == wire_only
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_encode_for_panel_with_preview_jpeg_crop_box_matches_encode_for_panel(
    sample_image_bytes,
):
    w, h = 1920, 1080
    source = sample_image_bytes(400, 300, color=(20, 150, 90))
    crop_box = (0.0, 0.0, 0.5, 1.0)

    wire_only = encode_for_panel(source, w, h, crop_box=crop_box, codec_id=CODEC_JPEG_Q90)
    wire, preview = encode_for_panel_with_preview(
        source, w, h, codec_id=CODEC_JPEG_Q90, crop_box=crop_box
    )

    assert wire == wire_only
    assert wire[:2] == b"\xff\xd8"
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_encode_for_panel_with_preview_no_crop_box_unchanged(sample_image_bytes):
    """Omitting crop_box (the default) must behave exactly as it did
    before this param existed -- no perturbation of the ordinary path."""
    w, h = 1200, 1600
    source = sample_image_bytes(400, 300)
    wire, preview = encode_for_panel_with_preview(source, w, h)
    assert len(wire) == (w * h) // 2
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


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


def test_text_skill_payload_spectra_bad_bin_with_rotation_raises():
    """Regression (issue #6): the soft-preview fallback above only applies
    when rotation=0, where the raw bin really is still valid wire bytes.
    With a nonzero rotation the rotate+repack step must actually run a
    decode of *spectra_bin*, so a malformed bin has to raise here too --
    silently returning the un-rotated bin would be packed at the wrong
    (composition, not native) size, the exact garbled-render bug this
    rotation support exists to prevent."""
    with pytest.raises(ValueError, match="bin is"):
        text_skill_payload_for_codec(
            b"not-a-bin", 1200, 1600, 90, CODEC_SPECTRA6_SPLIT_HALF, None
        )


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


def _exact_palette_marker_png(width: int, height: int) -> bytes:
    """A composition image built only from exact Spectra 6 palette colours
    (black background, a red quadrant) -- quantization is then dither-free
    and order-independent, so rotate-then-quantize and quantize-then-rotate
    are guaranteed to agree pixel-for-pixel, letting the two orderings be
    compared byte-exactly below."""
    import io

    from PIL import Image

    black = (25, 30, 33)
    red = (178, 19, 24)
    img = Image.new("RGB", (width, height), color=black)
    marker = Image.new("RGB", (width // 2, height // 2), color=red)
    img.paste(marker, (0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_text_skill_payload_spectra_rotates_to_native_buffer_without_rgb_png():
    """Regression: a locked-orientation Spectra frame's composition canvas
    (effective, orientation-swapped) must be rotated to the panel's native
    buffer before packing -- the renderer's own bin is composed unrotated,
    so text_skill_payload_for_codec is the only place this can happen. A
    frame is a registered native 1200x1600 panel; this skill's composition
    canvas is landscape 1600x1200 (orientation locked opposite native),
    rotation=90 per helpers.render_spec_for_entry."""
    from custom_components.digital_frames.image_converter import unpack_spectra6_bin

    eff_w, eff_h = 1600, 1200  # composition canvas (effective, swapped)
    native_w, native_h = 1200, 1600  # the panel's actual registered buffer

    composition_png = _exact_palette_marker_png(eff_w, eff_h)
    # What the pinned external renderer actually produces today: packed at
    # the composition size, with no knowledge of the frame's rotation.
    unrotated_bin = encode_for_panel(composition_png, eff_w, eff_h)

    wire, _preview = text_skill_payload_for_codec(
        unrotated_bin, eff_w, eff_h, 90, CODEC_SPECTRA6_SPLIT_HALF, None
    )

    # Must be repacked at the native (post-rotation) size, not left at the
    # composition size -- a bug here means the byte layout is transposed
    # relative to what the panel's raster expects.
    assert len(wire) == (native_w * native_h) // 2

    # Content must actually match a correct rotate-then-quantize-then-pack
    # of the same source (not just be *some* native-sized bytes). The
    # reference composes at the *effective* size (matching the renderer)
    # and applies the same canvas rotation image_converter._process would
    # for an ordinary photo send -- resize/rotate order must not matter
    # here since the source is built only from exact palette colours.
    reference_png = _exact_palette_marker_png(eff_w, eff_h)
    reference_bin = encode_for_panel(reference_png, eff_w, eff_h, rotation=90)
    assert wire == reference_bin

    # And it must actually differ from the (bug's) pass-through bytes --
    # otherwise this test would pass even with the old broken behavior.
    assert wire != unrotated_bin

    # Sanity: the returned bytes really do decode at the native size.
    decoded = unpack_spectra6_bin(wire, native_w, native_h)
    assert decoded.size == (native_w, native_h)


def test_text_skill_payload_spectra_rotates_to_native_buffer_with_rgb_png():
    """Same regression, but exercising the rgb_png-present branch (the path
    used whenever the renderer's full RGB composition PNG is available)."""
    eff_w, eff_h = 1600, 1200
    native_w, native_h = 1200, 1600

    composition_png = _exact_palette_marker_png(eff_w, eff_h)
    unrotated_bin = encode_for_panel(composition_png, eff_w, eff_h)

    wire, preview = text_skill_payload_for_codec(
        unrotated_bin, eff_w, eff_h, 90, CODEC_SPECTRA6_SPLIT_HALF, composition_png
    )

    assert len(wire) == (native_w * native_h) // 2
    reference_bin = encode_for_panel(composition_png, eff_w, eff_h, rotation=90)
    assert wire == reference_bin
    assert wire != unrotated_bin
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# CODEC_PNG (Samsung): regression -- used to silently fall through to the
# Spectra branch and return raw Spectra6-packed bytes labeled as valid PNG
# payload for any text/agenda Live skill assigned to a Samsung frame.
# ---------------------------------------------------------------------------


def test_text_skill_payload_png_from_spectra_bin_fallback(sample_image_bytes):
    w, h = 1200, 1600
    bin_bytes = encode_for_panel(sample_image_bytes(400, 300), w, h)
    wire, preview = text_skill_payload_for_codec(bin_bytes, w, h, 0, CODEC_PNG, None)
    assert wire[:8] == b"\x89PNG\r\n\x1a\n"
    assert wire != bin_bytes
    assert preview is not None
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_text_skill_payload_png_prefers_rgb_png():
    from PIL import Image
    import io

    w, h = 200, 100
    img = Image.new("RGB", (w, h), color=(12, 34, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rgb_png = buf.getvalue()

    # Invalid bin would fail if the RGB path were ignored.
    wire, preview = text_skill_payload_for_codec(
        b"not-a-valid-bin", w, h, 0, CODEC_PNG, rgb_png
    )
    assert wire[:8] == b"\x89PNG\r\n\x1a\n"
    assert preview is not None


def test_text_skill_payload_png_bad_bin_raises_without_rgb():
    with pytest.raises(ValueError, match="bin is"):
        text_skill_payload_for_codec(b"too-short", 1920, 1080, 0, CODEC_PNG, None)


def test_text_skill_payload_png_never_falls_through_to_spectra_bytes(
    sample_image_bytes,
):
    """The bug this guards: CODEC_PNG used to fall through to the 'Spectra
    wire payload' branch (only CODEC_JPEG_Q90 was special-cased), so a
    Samsung frame's skill send returned raw Spectra6 nibble-packed bytes
    mislabeled as PNG."""
    w, h = 1200, 1600
    bin_bytes = encode_for_panel(sample_image_bytes(400, 300), w, h)
    wire, _preview = text_skill_payload_for_codec(bin_bytes, w, h, 0, CODEC_PNG, None)
    # A real PNG never starts with the Spectra bin's own bytes.
    assert wire != bin_bytes
    assert wire.startswith(b"\x89PNG\r\n\x1a\n")
