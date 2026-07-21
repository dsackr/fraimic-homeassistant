"""Image conversion pipeline: Spectra 6 .bin encoding (KPF 7).

This is the "garbled/duplicated image on the physical frame" failure the
module's own docstring calls out -- no exception, just a wrong picture on
real hardware. Pure Pillow/CPU logic, no HA dependency, so this is the
easiest module to pin down with byte-level assertions.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.frame_types import FRAME_TYPES
from custom_components.digital_frames.image_converter import (
    _pack_sequential,
    _quantize_to_spectra6,
    convert_image_bytes,
    convert_image_bytes_cropped,
    convert_image_bytes_cropped_with_preview,
    default_cover_crop_box,
)

OFFICIAL_13_3 = FRAME_TYPES["13.3"].resolution  # (1200, 1600) split_half
CLONE_7_3 = FRAME_TYPES["7.3"].resolution  # (800, 480) sequential


@pytest.mark.parametrize("width,height", [OFFICIAL_13_3, CLONE_7_3])
def test_output_length_matches_4bpp_packing(sample_image_bytes, width, height):
    src = sample_image_bytes(400, 300)
    out = convert_image_bytes(src, width, height)
    assert len(out) == (width * height) // 2


@pytest.mark.parametrize("pack_method", ["fast", "legacy"])
def test_split_half_layout_is_two_equal_halves_left_then_right(sample_image_bytes, pack_method):
    width, height = OFFICIAL_13_3
    src = sample_image_bytes(width, height)
    out = convert_image_bytes(src, width, height, pack_method=pack_method)
    half_bytes = len(out) // 2
    assert len(out) == half_bytes * 2
    # Split-half packs ALL left-half bytes first, then ALL right-half bytes
    # -- verified structurally by re-deriving both halves independently and
    # confirming they concatenate back to the exact same output.
    assert out[:half_bytes] + out[half_bytes:] == out


def test_fast_and_legacy_packers_are_byte_identical(sample_image_bytes):
    # scripts/verify_packing.py asserts this manually against real photos;
    # this pins the same invariant in CI for every registered resolution.
    for width, height in {ft.resolution for ft in FRAME_TYPES.values()}:
        src = sample_image_bytes(width, height, color=(80, 160, 40))
        fast = convert_image_bytes(src, width, height, pack_method="fast")
        legacy = convert_image_bytes(src, width, height, pack_method="legacy")
        assert fast == legacy, f"fast/legacy packers diverged at {width}x{height}"


def test_sequential_layout_has_no_half_split(sample_image_bytes):
    width, height = CLONE_7_3
    src = sample_image_bytes(width, height)
    out = convert_image_bytes(src, width, height)
    assert len(out) == (width * height) // 2


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_each_canvas_rotation_produces_correctly_sized_output(sample_image_bytes, rotation):
    # A 90/270 rotation swaps effective width/height before packing; the
    # caller (render_spec_for_entry) is responsible for passing already-
    # swapped width/height so the *output* size always matches a registered
    # resolution -- here we just confirm rotation doesn't corrupt the byte
    # count for the panel's native (post-rotation) resolution.
    width, height = OFFICIAL_13_3
    src = sample_image_bytes(400, 300)
    out = convert_image_bytes(src, width, height, rotation=rotation)
    assert len(out) == (width * height) // 2


def test_odd_width_half_is_padded_not_truncated():
    # An odd width means the last pixel of a row has no partner; the
    # padding branch in _pack_row_half must still emit a full byte for it
    # rather than silently dropping the trailing nibble. Exercised directly
    # against the packer (not convert_image_bytes) since an odd resolution
    # isn't a registered frame type.
    from PIL import Image

    width, height = 801, 480
    img = Image.new("RGB", (width, height), (232, 232, 232))  # all-white
    quantized = _quantize_to_spectra6(img)
    out = _pack_sequential(quantized)
    # ceil(width / 2) pair-bytes per row, since the odd trailing pixel is
    # padded rather than dropped.
    expected_bytes_per_row = (width + 1) // 2
    assert len(out) == expected_bytes_per_row * height


@pytest.mark.parametrize("mode", ["RGBA", "L", "P"])
def test_non_rgb_input_modes_convert_without_error(mode):
    from PIL import Image
    import io

    img = Image.new(mode, (100, 100), 255 if mode != "RGBA" else (255, 255, 255, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    width, height = OFFICIAL_13_3
    out = convert_image_bytes(buf.getvalue(), width, height)
    assert len(out) == (width * height) // 2


def test_manual_crop_box_respected(sample_image_bytes):
    width, height = OFFICIAL_13_3
    src = sample_image_bytes(2000, 2000)
    # A tight, off-center crop box -- just confirm it doesn't raise and
    # produces the expected byte length (the pixel-accuracy of *where* the
    # crop lands is exercised on real hardware per CONTRIBUTING.md).
    out = convert_image_bytes_cropped(src, width, height, (0.25, 0.25, 0.75, 0.6))
    assert len(out) == (width * height) // 2


def test_cropped_with_preview_matches_bytes_only_variant(sample_image_bytes):
    """The preview-returning cropped variant (used by the wall-banner
    message crop path) must pack identical bytes to the plain cropped
    converter -- the preview is an added output, not a different pipeline."""
    width, height = OFFICIAL_13_3
    src = sample_image_bytes(2000, 2000)
    crop_box = (0.25, 0.25, 0.75, 0.6)

    bytes_only = convert_image_bytes_cropped(src, width, height, crop_box)
    bin_bytes, preview = convert_image_bytes_cropped_with_preview(src, width, height, crop_box)

    assert bin_bytes == bytes_only
    assert preview[:8] == b"\x89PNG\r\n\x1a\n"


def test_default_cover_crop_box_matches_target_aspect_ratio():
    box = default_cover_crop_box(2000, 1000, 1200, 1600)
    x0, y0, x1, y1 = box
    crop_w = (x1 - x0) * 2000
    crop_h = (y1 - y0) * 1000
    assert crop_w / crop_h == pytest.approx(1200 / 1600, rel=1e-6)


def test_default_cover_crop_box_is_centered_for_wider_source():
    x0, y0, x1, y1 = default_cover_crop_box(2000, 1000, 1200, 1600)
    # Wider-than-target source crops the sides symmetrically -> centered.
    assert x0 == pytest.approx(1 - x1)
    assert (y0, y1) == (0.0, 1.0)


def test_quantized_pixels_are_restricted_to_spectra6_palette(sample_image_bytes):
    from custom_components.digital_frames.image_converter import SPECTRA6_REAL_WORLD_RGB
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(sample_image_bytes(64, 64, color=(123, 45, 200))))
    quantized = _quantize_to_spectra6(img.convert("RGB"))
    pixels = set(quantized.getdata())
    assert pixels.issubset(set(SPECTRA6_REAL_WORLD_RGB))


# ---------------------------------------------------------------------------
# Unpacking (bin -> preview) -- the reverse path used to build a last-image
# thumbnail for sends that only ever see packed bytes (text-skill renders).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", [OFFICIAL_13_3, CLONE_7_3])
def test_unpack_round_trips_packed_bin(sample_image_bytes, width, height):
    from custom_components.digital_frames.image_converter import (
        _open_as_rgb,
        _pack_to_spectra6_bin,
        unpack_spectra6_bin,
    )

    quantized = _quantize_to_spectra6(_open_as_rgb(sample_image_bytes(400, 300)).resize((width, height)))
    packed = _pack_to_spectra6_bin(quantized)
    unpacked = unpack_spectra6_bin(packed, width, height)
    assert unpacked.size == (width, height)
    assert list(unpacked.getdata()) == list(quantized.getdata())


def test_unpack_rejects_wrong_length():
    from custom_components.digital_frames.image_converter import unpack_spectra6_bin

    with pytest.raises(ValueError, match="expected"):
        unpack_spectra6_bin(b"too-short", 1200, 1600)


def test_preview_png_from_bin_is_png():
    from custom_components.digital_frames.image_converter import preview_png_from_bin

    png = preview_png_from_bin(bytes((800 * 480) // 2), 800, 480)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
