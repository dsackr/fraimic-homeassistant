"""
Spectra 6 image converter for Fraimic e-ink frames.

Converts arbitrary images (any format Pillow supports) to the raw binary format
expected by the target panel. All Fraimic-supported panels share the same 4bpp
Spectra 6 palette, but NOT the same byte layout -- see "Binary format
specification" below. Getting this wrong doesn't error, it silently produces a
garbled/duplicated image on the physical frame (confirmed the hard way: see
the 7.3" panel investigation that led to declaring byte_layout explicitly
per frame type in frame_types.py).

Binary format specification
----------------------------
Common to every panel:
- 4 bits per pixel (one nibble)
- 2 pixels packed per byte: high nibble = first pixel of the pair, low
  nibble = second
- Pixels are scanned in normal row-major order: y from top to bottom, x from
  left to right
- Nibble values map to Spectra 6 colors (note: value 4 is unused by the hardware):
    0 = Black
    1 = White
    2 = Yellow
    3 = Red
    5 = Blue
    6 = Green

Byte ordering differs by physical panel construction, declared per frame
type in frame_types.py (FrameType.byte_layout) rather than inferred:

- **Split-half** (confirmed against Fraimic's own reference converter,
  github.com/Fraimic/fraimic_bin_converter, EL133UF1 / Spectra 6 13.3"):
  each row is split into a LEFT half (columns 0 .. width//2 - 1) and a RIGHT
  half (columns width//2 .. width - 1). ALL left-half bytes for the entire
  image come first (every row, top to bottom), followed by ALL right-half
  bytes (every row, top to bottom) -- matching a panel physically built from
  two side-by-side half-width e-ink halves, each driven from its own
  contiguous block of the buffer. Used by the 13.1"/13.3" (EL133UF1) and
  31.5" panels.
- **Sequential** (confirmed against Waveshare's own epd7in3e.py reference
  driver for the 7.3" E6 panel): one single contiguous buffer, pixel pairs
  packed in plain left-to-right, top-to-bottom order with no half-split.
  Used by the 7.3" panel.

Conversion pipeline
--------------------
1. Open image (any format Pillow supports)
2. Handle a landscape/portrait mismatch between image and target:
   - default (unlocked, the Fraimic way): rotate the image 90 degrees so it
     fills the frame sideways at full size
   - locked=True (frame has an orientation lock): keep the image upright
     and let step 3's centered cover-crop trim it to the target shape
3. Scale to cover the target dimensions (preserving aspect ratio) and
   center -- overflow is cropped
4. Optionally rotate the finished canvas (90/180/270) -- used for frames
   physically hung in their non-native orientation and/or upside down
5. Quantize to the 6 Spectra 6 real-world colors using Floyd-Steinberg dithering
6. Pack pixels into the nibble format described above, using the byte
   ordering that matches the final resolution's physical panel
"""

from __future__ import annotations

import io
from typing import Tuple

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Pillow is required for image conversion. "
        "Install it with: pip install Pillow"
    ) from exc

try:  # Optional: makes the "fast" packer fully vectorized. Not required.
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

from .frame_types import LAYOUT_SPLIT_HALF, frame_type_for_resolution


# ---------------------------------------------------------------------------
# Palette constants
# ---------------------------------------------------------------------------

# Real-world RGB values measured from an actual Spectra 6 display under D65
# lighting (from the epdoptimize project). These are used as the quantization
# target so that dithering error diffusion is computed in perceptually accurate
# colour space rather than against idealised primaries.
SPECTRA6_REAL_WORLD_RGB: Tuple[Tuple[int, int, int], ...] = (
    (25, 30, 33),     # Black   → nibble 0
    (232, 232, 232),  # White   → nibble 1
    (239, 222, 68),   # Yellow  → nibble 2
    (178, 19, 24),    # Red     → nibble 3
    (33, 87, 186),    # Blue    → nibble 5
    (18, 95, 32),     # Green   → nibble 6
)

# Raw nibble values that the Spectra 6 hardware expects for each palette entry.
# Note that value 4 is intentionally skipped (unused by the hardware).
SPECTRA6_NIBBLE_VALUES: Tuple[int, ...] = (0, 1, 2, 3, 5, 6)

# Sanity check: palette and nibble tables must stay in sync.
assert len(SPECTRA6_REAL_WORLD_RGB) == len(SPECTRA6_NIBBLE_VALUES)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_palette_image() -> "Image.Image":
    """
    Build a single-pixel palette image used by Pillow's quantize() method.

    The palette must be padded to 256 entries (768 bytes); unused slots are
    filled with the first colour (black) so that any accidental match maps to
    a valid colour rather than an arbitrary one.
    """
    pal_image = Image.new("P", (1, 1))
    flat_palette = tuple(v for rgb in SPECTRA6_REAL_WORLD_RGB for v in rgb)
    # Pad to 256 colours × 3 channels = 768 bytes.
    padding_colour = SPECTRA6_REAL_WORLD_RGB[0]  # black
    padding = padding_colour * (256 - len(SPECTRA6_REAL_WORLD_RGB))
    pal_image.putpalette(flat_palette + padding)
    return pal_image


def _resize_cover_centered(
    image: "Image.Image",
    target_width: int,
    target_height: int,
) -> "Image.Image":
    """
    Scale *image* (preserving aspect ratio) so it fully covers
    *target_width* × *target_height*, then center it on the canvas. Whatever
    overflows the canvas is cropped away -- i.e. a centered "cover" crop, not
    a letterbox. (Historically misnamed: this function has always used
    max-scaling, so it has always cropped rather than padded.)
    """
    orig_w, orig_h = image.size

    # Scale so that the image covers the entire target area.
    scale = max(target_width / orig_w, target_height / orig_h)
    scaled_w = int(orig_w * scale)
    scaled_h = int(orig_h * scale)

    resized = image.resize((scaled_w, scaled_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    left = (target_width - scaled_w) // 2
    top = (target_height - scaled_h) // 2
    canvas.paste(resized, (left, top))
    return canvas


def _crop_to_box(
    image: "Image.Image",
    crop_box: "Tuple[float, float, float, float]",
) -> "Image.Image":
    """
    Crop *image* to the normalized rectangle *crop_box* = (x0, y0, x1, y1),
    where each value is a fraction (0.0-1.0) of the source image's full
    width/height. Used by the manual-crop path (as opposed to the automatic
    letterbox path above) -- the caller is responsible for choosing a box
    whose aspect ratio already matches the eventual target width/height, so
    no padding or distortion is introduced by the subsequent resize.

    Coordinates are clamped to [0, 1] and reordered/widened as needed so the
    result is always a valid, non-empty box within the image bounds.
    """
    orig_w, orig_h = image.size
    x0, y0, x1, y1 = crop_box

    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))

    left = int(round(x0 * orig_w))
    top = int(round(y0 * orig_h))
    right = int(round(x1 * orig_w))
    bottom = int(round(y1 * orig_h))

    # Guarantee at least a 1px box even if rounding collapsed it to nothing.
    right = max(right, left + 1)
    bottom = max(bottom, top + 1)
    right = min(right, orig_w)
    bottom = min(bottom, orig_h)
    left = min(left, right - 1)
    top = min(top, bottom - 1)

    return image.crop((left, top, right, bottom))


def default_cover_crop_box(
    orig_width: int, orig_height: int, target_width: int, target_height: int
) -> "Tuple[float, float, float, float]":
    """
    Compute a centred crop rectangle (normalized 0-1 coordinates against the
    original image) whose aspect ratio exactly matches
    *target_width* : *target_height*, sized as large as possible without
    exceeding the original image -- i.e. the same centred "cover" framing
    _resize_with_letterbox would produce if it cropped instead of padding.

    This is the starting point the crop editor shows for an image that
    doesn't have a saved crop yet for the chosen frame, and exactly the
    framing the automatic (no-saved-crop) locked-orientation path produces.
    """
    target_ratio = target_width / target_height
    orig_ratio = orig_width / orig_height

    if orig_ratio > target_ratio:
        # Original is relatively wider than the target -- crop the sides.
        crop_w = orig_height * target_ratio
        crop_h = float(orig_height)
    else:
        # Original is relatively taller than the target -- crop top/bottom.
        crop_w = float(orig_width)
        crop_h = orig_width / target_ratio

    x0 = (orig_width - crop_w) / 2 / orig_width
    y0 = (orig_height - crop_h) / 2 / orig_height
    return (x0, y0, 1 - x0, 1 - y0)


def _auto_rotate(
    image: "Image.Image",
    target_width: int,
    target_height: int,
) -> "Image.Image":
    """
    Rotate *image* by 90° if its landscape/portrait orientation does not match
    the target dimensions, so that the image fills the frame as well as
    possible without unnecessary black bars.

    The rotation direction (90° vs 270°) is chosen to match the reference
    implementation default (270°, i.e. clockwise 90°).
    """
    img_w, img_h = image.size
    img_is_landscape = img_w > img_h
    tgt_is_landscape = target_width > target_height

    if img_is_landscape != tgt_is_landscape:
        # Rotate 270° clockwise (= 90° counter-clockwise) with expand so the
        # canvas resizes to match the new orientation.
        image = image.rotate(270, expand=True)

    return image


def _quantize_to_spectra6(image: "Image.Image") -> "Image.Image":
    """
    Quantize *image* (must be RGB) to the 6 Spectra 6 real-world colours using
    Floyd-Steinberg error-diffusion dithering.

    Returns an RGB image where every pixel is one of the six palette entries in
    :data:`SPECTRA6_REAL_WORLD_RGB`.
    """
    pal_image = _build_palette_image()
    # quantize() returns a palette-mode image; convert back to RGB so that
    # pixel values are plain (r, g, b) tuples for the packing step.
    return image.quantize(
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=pal_image,
    ).convert("RGB")


def _nibble_for_pixel(quantized_image: "Image.Image", x: int, y: int) -> int:
    """Look up the Spectra 6 nibble value for the pixel at (x, y)."""
    r, g, b = quantized_image.load()[x, y]
    try:
        index = SPECTRA6_REAL_WORLD_RGB.index((r, g, b))
    except ValueError:
        raise ValueError(
            f"Unexpected pixel colour ({r}, {g}, {b}) at ({x}, {y}). "
            "Quantization should have constrained all pixels to the "
            "Spectra 6 palette."
        )
    return SPECTRA6_NIBBLE_VALUES[index]


def _pack_row_half(
    quantized_image: "Image.Image", y: int, start_x: int, end_x: int
) -> bytes:
    """Pack columns [start_x, end_x) of row *y* into bytes (ascending pairs)."""
    out = bytearray()
    width = quantized_image.width
    for x in range(start_x, end_x, 2):
        high_nibble = _nibble_for_pixel(quantized_image, x, y)
        odd_x = x + 1
        if odd_x < end_x and odd_x < width:
            low_nibble = _nibble_for_pixel(quantized_image, odd_x, y)
        else:
            # Odd-width half — pad the missing partner pixel with white.
            low_nibble = SPECTRA6_NIBBLE_VALUES[
                SPECTRA6_REAL_WORLD_RGB.index((232, 232, 232))
            ]
        out.append((high_nibble << 4) | low_nibble)
    return bytes(out)


def _pack_to_spectra6_bin(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized RGB image into the raw Spectra 6 binary format, using
    the PanelCodec declared for a registered frame type at this image's
    resolution (see frame_types.py / panel_codec.py and the module docstring).

    :param quantized_image: RGB image whose pixels are restricted to the six
        entries of :data:`SPECTRA6_REAL_WORLD_RGB`.
    :returns: Raw bytes ready to be sent as a ``.bin`` file.
    :raises ValueError: If a pixel colour does not match any palette entry
        (indicates a bug in the quantization step), or if no registered
        frame type has this image's resolution.
    """
    # Codec selection: resolution → FrameType → byte_layout (split_half for
    # official panels, sequential for 7.3"). Callers that only have geometry
    # land here; library paths should prefer panel_codec.encode_for_panel so
    # the seam is obvious at the call site.
    layout = frame_type_for_resolution(
        quantized_image.width, quantized_image.height
    ).byte_layout
    if layout == LAYOUT_SPLIT_HALF:
        return _pack_split_halves(quantized_image)
    return _pack_sequential(quantized_image)


def _pack_split_halves(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for a panel built from two independent
    half-width e-ink halves (confirmed against Fraimic's own reference
    converter for the EL133UF1 / 13.1"/13.3" and 31.5" panels): rows are
    visited top to bottom, columns left to right within each half. Each row
    is split at the midpoint into a left half and a right half. All
    left-half bytes for the whole image are emitted first (row by row, top
    to bottom), followed by all right-half bytes (row by row, top to
    bottom) — matching each half's own contiguous block of the buffer.
    """
    width = quantized_image.width
    height = quantized_image.height
    half = width // 2

    left_bytes = bytearray()
    right_bytes = bytearray()

    for y in range(height):
        left_bytes.extend(_pack_row_half(quantized_image, y, 0, half))
        right_bytes.extend(_pack_row_half(quantized_image, y, half, width))

    return bytes(left_bytes) + bytes(right_bytes)


def _pack_sequential(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for a panel with a single contiguous buffer
    (confirmed against Waveshare's own epd7in3e.py reference driver for the
    7.3" E6 panel): plain row-major order, no half-split.
    """
    width = quantized_image.width
    height = quantized_image.height
    out = bytearray()
    for y in range(height):
        out.extend(_pack_row_half(quantized_image, y, 0, width))
    return bytes(out)


# ---------------------------------------------------------------------------
# Fast packing path (pack_method="fast")
#
# Same output bytes as the legacy per-pixel path above, produced from
# quantize()'s palette-index image directly instead of the RGB round-trip:
# bytes.translate() maps palette indices to hardware nibbles in C, and pair
# packing is vectorized (numpy when available, a slicing zip loop otherwise).
# The legacy path does ~10M Python-level operations for a 1200x1600 panel
# (a .load()[x, y] call plus a linear tuple .index() per pixel); this path
# does a handful. Byte-identity between the two is asserted by
# scripts/verify_packing.py -- run it after touching either path.
# ---------------------------------------------------------------------------

# P-mode palette index → hardware nibble. quantize() indices 0-5 are the six
# colours in SPECTRA6_REAL_WORLD_RGB order; indices 6-255 are the black
# padding entries from _build_palette_image, which the legacy RGB round-trip
# collapses to black (tuple.index returns the first match), so they map to
# black's nibble here too.
_P_INDEX_TO_NIBBLE = bytes(
    list(SPECTRA6_NIBBLE_VALUES)
    + [SPECTRA6_NIBBLE_VALUES[0]] * (256 - len(SPECTRA6_NIBBLE_VALUES))
)

# White pads the missing partner pixel of an odd-width (half-)row -- mirrors
# the hardcoded (232, 232, 232) lookup in _pack_row_half.
_WHITE_NIBBLE = SPECTRA6_NIBBLE_VALUES[SPECTRA6_REAL_WORLD_RGB.index((232, 232, 232))]


def _pack_nibble_pairs(nibbles: bytes) -> bytes:
    """Pack an even-length sequence of nibble values two-per-byte
    (high nibble = first of the pair)."""
    if _np is not None:
        arr = _np.frombuffer(nibbles, dtype=_np.uint8)
        return ((arr[0::2] << 4) | arr[1::2]).tobytes()
    return bytes(
        (nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2)
    )


def _pack_segments_fast(
    nibbles: bytes, width: int, height: int, start_x: int, end_x: int
) -> bytes:
    """Fast equivalent of running _pack_row_half over every row for columns
    [start_x, end_x): rows are sliced out of the row-major nibble buffer,
    odd-width segments padded with white, then pair-packed in one pass."""
    seg_w = end_x - start_x
    if seg_w == width and seg_w % 2 == 0:
        # Full-width, even: the buffer is already one contiguous even run.
        return _pack_nibble_pairs(nibbles)
    pad = bytes([_WHITE_NIBBLE]) if seg_w % 2 else b""
    rows = [
        nibbles[y * width + start_x : y * width + end_x] + pad
        for y in range(height)
    ]
    return _pack_nibble_pairs(b"".join(rows))


def _pack_p_image_fast(p_image: "Image.Image") -> bytes:
    """Pack a P-mode quantized image (palette indices, straight from
    quantize()) into the Spectra 6 binary format. Layout dispatch mirrors
    _pack_to_spectra6_bin."""
    width, height = p_image.size
    nibbles = p_image.tobytes().translate(_P_INDEX_TO_NIBBLE)
    layout = frame_type_for_resolution(width, height).byte_layout
    if layout == LAYOUT_SPLIT_HALF:
        half = width // 2
        return (
            _pack_segments_fast(nibbles, width, height, 0, half)
            + _pack_segments_fast(nibbles, width, height, half, width)
        )
    return _pack_segments_fast(nibbles, width, height, 0, width)


def _quantize_to_spectra6_p(image: "Image.Image") -> "Image.Image":
    """Identical quantization to _quantize_to_spectra6 but returns the
    P-mode (palette-index) image the fast packer consumes, instead of
    converting back to RGB."""
    return image.quantize(
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=_build_palette_image(),
    )


def _open_as_rgb(source: "str | bytes") -> "Image.Image":
    """
    Open an image from a file path or raw bytes and return it in RGB mode.

    Handles palette, grayscale, and RGBA modes transparently by compositing
    onto a white background before converting.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        image = Image.open(io.BytesIO(source))
    else:
        image = Image.open(source)

    # Apply EXIF orientation before anything else so that auto-rotate works on
    # the visual orientation rather than the encoded orientation.
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass  # Older Pillow versions or images without EXIF; proceed anyway.

    # Composite RGBA onto white so transparency becomes the background colour.
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        mask = image.split()[-1]  # alpha channel
        background.paste(image.convert("RGB"), mask=mask)
        return background

    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_image(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> bytes:
    """
    Convert an image file to the raw Spectra 6 binary format.

    The full conversion pipeline is:

    1. Open the image (any format Pillow supports; EXIF orientation applied).
    2. If the image and target orientations mismatch: rotate the image
       sideways (default) or, with *locked*, keep it upright and rely on the
       cover-crop in step 3.
    3. Scale-to-cover *width* × *height*, centered (overflow cropped).
    4. Apply *rotation* (canvas rotation, e.g. 90/180/270 for frames hung
       rotated / upside down).
    5. Quantize to the 6 Spectra 6 palette colours with Floyd-Steinberg
       dithering.
    6. Pack pixels into 4-bit nibbles (see module docstring).

    :param image_path: Path to the source image file.
    :param width: Composition width in pixels (the frame's effective width).
    :param height: Composition height in pixels.
    :param rotation: Canvas rotation in degrees CCW (0/90/180/270), applied
        after composition. The packed output dimensions are the post-rotation
        dimensions, which must be a registered panel resolution.
    :param locked: True when the target frame has an orientation lock --
        mismatched-orientation images are auto-cropped upright instead of
        being rotated sideways.
    :returns: Raw bytes in Spectra 6 ``.bin`` format, ready for the Fraimic
        API.  The length will be ``(width * height) // 2`` bytes.
    :raises FileNotFoundError: If *image_path* does not exist.
    :raises ImportError: If Pillow is not installed.
    """
    image = _open_as_rgb(image_path)
    bin_bytes, _quantized = _process(image, width, height, rotation, locked)
    return bin_bytes


def convert_image_with_preview(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> "Tuple[bytes, bytes]":
    """
    Like :func:`convert_image`, but also returns a small PNG preview of the
    final quantized image (see :func:`_encode_preview_png`) for callers that
    need a UI thumbnail of what was sent -- currently the generic
    ``send_image`` service, which resolves an arbitrary ``media_content_id``
    rather than a Library image_id and so can't reuse the Library's
    original-image thumbnail endpoint.

    :returns: ``(bin_bytes, preview_png_bytes)``.
    """
    image = _open_as_rgb(image_path)
    bin_bytes, quantized = _process(image, width, height, rotation, locked)
    return bin_bytes, _encode_preview_png(quantized)


def convert_image_bytes(
    image_data: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
) -> bytes:
    """
    Convert raw image bytes to the raw Spectra 6 binary format.

    Accepts any image format that Pillow can decode (JPEG, PNG, WebP, GIF,
    BMP, TIFF, …). See :func:`convert_image` for parameter details and
    :func:`_process` for *pack_method*.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, _quantized = _process(
        image, width, height, rotation, locked, pack_method
    )
    return bin_bytes


def convert_image_bytes_with_preview(
    image_data: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> "Tuple[bytes, bytes]":
    """
    Like :func:`convert_image_bytes`, but also returns a small PNG preview of
    the final quantized image. See :func:`convert_image_with_preview` for why
    this exists -- used here by the raw-upload HTTP view
    (FraimicSendImageView), which also has no Library image_id to hand.

    :returns: ``(bin_bytes, preview_png_bytes)``.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, quantized = _process(image, width, height, rotation, locked)
    return bin_bytes, _encode_preview_png(quantized)


def _encode_preview_png(image: "Image.Image") -> bytes:
    """
    Encode *image* (already quantized to the Spectra 6 palette) as a small PNG,
    downscaled to icon size. Used to give callers that don't have a Library
    image_id (e.g. the generic send_image service / media browser sends) a
    UI-viewable thumbnail of what actually went to the frame, without needing
    the original source file to still be reachable later.
    """
    preview = image.copy()
    preview.thumbnail((240, 240), Image.LANCZOS)
    buf = io.BytesIO()
    preview.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumbnail(raw_bytes: bytes, edge: int, quality: int = 82) -> bytes:
    """
    Downscale an original image to at most *edge* px on its longest side and
    encode it as JPEG. Serves the panel's grid/picker tiles (see
    FraimicLibraryImageView's ?thumb= handling) so they never have to download
    and decode multi-MB originals client-side.
    """
    image = _open_as_rgb(raw_bytes)
    image.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _process(
    image: "Image.Image",
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
) -> "Tuple[bytes, Image.Image]":
    """Shared implementation used by both public entry points. Returns the
    packed bytes alongside the final quantized image so preview-generating
    callers can reuse it without re-running the pipeline.

    pack_method="fast" (the default) packs through the vectorized path;
    "legacy" is the historical per-pixel path, kept temporarily as an
    escape hatch (reachable via the panel's ?packer=legacy override). The
    two produce identical bytes -- proven by scripts/verify_packing.py and
    confirmed pixel-identical on real frames (2026-07) -- so legacy plus
    the A/B switches can be removed in a future release."""
    if not locked:
        # The Fraimic way: a mismatched image lies sideways at full size.
        image = _auto_rotate(image, width, height)
    # Locked: no source rotation -- the centered cover-crop below trims a
    # mismatched image to the target shape while keeping it upright.
    image = _resize_cover_centered(image, width, height)
    if rotation:
        image = image.rotate(rotation, expand=True)
    if pack_method == "fast":
        p_image = _quantize_to_spectra6_p(image)
        return _pack_p_image_fast(p_image), p_image.convert("RGB")
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image), image


# ---------------------------------------------------------------------------
# Unpacking (bin → preview) -- the reverse of the packers above, used to give
# send paths that only ever see packed bytes (the xOTD/skill text renderer,
# whose pinned subprocess emits xotd.bin directly) a UI preview of what went
# to the frame. Without this, a text-skill send has neither a library
# image_id nor a thumbnail, and the frame's "last image" state goes blank.
# ---------------------------------------------------------------------------

# hardware nibble value → palette index (SPECTRA6_NIBBLE_VALUES inverted).
# Unknown nibbles (4, 7-15) map to white so a corrupt byte degrades visibly
# but harmlessly instead of raising.
_NIBBLE_TO_INDEX = bytes(
    SPECTRA6_NIBBLE_VALUES.index(n) if n in SPECTRA6_NIBBLE_VALUES else 1
    for n in range(16)
)
# byte → palette index of its high/low nibble, for bytes.translate (C speed).
_HI_NIBBLE_INDEX = bytes(_NIBBLE_TO_INDEX[b >> 4] for b in range(256))
_LO_NIBBLE_INDEX = bytes(_NIBBLE_TO_INDEX[b & 0xF] for b in range(256))


def _unpack_nibble_pairs(packed: bytes) -> bytes:
    """Expand nibble-packed bytes into one palette-index byte per pixel."""
    out = bytearray(len(packed) * 2)
    out[0::2] = packed.translate(_HI_NIBBLE_INDEX)
    out[1::2] = packed.translate(_LO_NIBBLE_INDEX)
    return bytes(out)


def unpack_spectra6_bin(bin_bytes: bytes, width: int, height: int) -> "Image.Image":
    """
    Decode a packed Spectra 6 ``.bin`` back into an RGB image -- the inverse
    of :func:`_pack_to_spectra6_bin` for a *width* × *height* panel. The byte
    layout is looked up like the packers do; an unregistered resolution
    falls back to split-half, matching the renderer fallback in
    skills.SkillManager._async_render_text.

    :raises ValueError: If *bin_bytes* isn't exactly ``width*height//2`` long.
    """
    expected = (width * height) // 2
    if len(bin_bytes) != expected:
        raise ValueError(
            f"bin is {len(bin_bytes)} bytes, expected {expected} for {width}x{height}"
        )
    try:
        layout = frame_type_for_resolution(width, height).byte_layout
    except ValueError:
        layout = LAYOUT_SPLIT_HALF

    indices = _unpack_nibble_pairs(bin_bytes)

    if layout == LAYOUT_SPLIT_HALF:
        # left-half rows first, then right-half rows -- re-interleave.
        half = width // 2
        left = indices[: half * height]
        right = indices[half * height :]
        rows = bytearray(width * height)
        for y in range(height):
            rows[y * width : y * width + half] = left[y * half : (y + 1) * half]
            rows[y * width + half : (y + 1) * width] = right[y * half : (y + 1) * half]
        indices = bytes(rows)

    image = Image.frombytes("P", (width, height), indices)
    image.putpalette(_build_palette_image().getpalette())
    return image.convert("RGB")


def preview_png_from_bin(bin_bytes: bytes, width: int, height: int) -> bytes:
    """Small PNG preview of a packed ``.bin`` (see :func:`unpack_spectra6_bin`
    and :func:`_encode_preview_png`)."""
    return _encode_preview_png(unpack_spectra6_bin(bin_bytes, width, height))


def convert_image_cropped(
    image_path: str,
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
) -> bytes:
    """
    Convert an image file to Spectra 6 binary using a manually-chosen crop
    rectangle instead of the automatic letterbox path.

    :param image_path: Path to the source image file.
    :param width: Target display width in pixels.
    :param height: Target display height in pixels.
    :param crop_box: (x0, y0, x1, y1), normalized 0.0-1.0 against the
        source image's full dimensions (post EXIF-orientation). The caller
        (the crop editor UI) is responsible for keeping this box's aspect
        ratio matched to width:height.
    :param rotation: Optional extra rotation in degrees (e.g. 180).
    :returns: Raw bytes in Spectra 6 ``.bin`` format.
    """
    image = _open_as_rgb(image_path)
    return _process_cropped(image, width, height, crop_box, rotation)


def convert_image_bytes_cropped(
    image_data: bytes,
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
    pack_method: str = "fast",
) -> bytes:
    """
    Convert raw image bytes to Spectra 6 binary using a manually-chosen crop
    rectangle instead of the automatic letterbox path. See
    :func:`convert_image_cropped` for parameter details and :func:`_process`
    for *pack_method*.
    """
    image = _open_as_rgb(image_data)
    return _process_cropped(image, width, height, crop_box, rotation, pack_method)


def _process_cropped(
    image: "Image.Image",
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
    pack_method: str = "fast",
) -> bytes:
    img_w, img_h = image.width, image.height
    x0, y0, x1, y1 = crop_box
    w = x1 - x0
    h = y1 - y0
    if w > 0 and h > 0:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        # Target aspect ratio in normalized coordinates:
        # nw / nh = (width * img_h) / (height * img_w)
        target_ar_norm = (width * img_h) / (height * img_w)

        if w / h > target_ar_norm:
            # Crop box is too wide, trim the width
            nh = h
            nw = h * target_ar_norm
        else:
            # Crop box is too tall, trim the height
            nw = w
            nh = w / target_ar_norm

        x0 = max(0.0, min(cx - nw / 2.0, 1.0))
        x1 = max(0.0, min(cx + nw / 2.0, 1.0))
        y0 = max(0.0, min(cy - nh / 2.0, 1.0))
        y1 = max(0.0, min(cy + nh / 2.0, 1.0))
        crop_box = (x0, y0, x1, y1)

    image = _crop_to_box(image, crop_box)
    image = image.resize((width, height), Image.LANCZOS)
    if rotation:
        image = image.rotate(rotation, expand=True)
    if pack_method == "fast":
        return _pack_p_image_fast(_quantize_to_spectra6_p(image))
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image)
