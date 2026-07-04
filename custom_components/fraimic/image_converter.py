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

from .frame_types import LAYOUT_SPLIT_HALF, byte_layout_for_resolution


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
    the byte ordering declared for a registered frame type at this image's
    resolution (see frame_types.py and the module docstring).

    :param quantized_image: RGB image whose pixels are restricted to the six
        entries of :data:`SPECTRA6_REAL_WORLD_RGB`.
    :returns: Raw bytes ready to be sent as a ``.bin`` file.
    :raises ValueError: If a pixel colour does not match any palette entry
        (indicates a bug in the quantization step), or if no registered
        frame type has this image's resolution.
    """
    layout = byte_layout_for_resolution(quantized_image.width, quantized_image.height)
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
    return _process(image, width, height, rotation, locked)


def convert_image_bytes(
    image_data: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> bytes:
    """
    Convert raw image bytes to the raw Spectra 6 binary format.

    Accepts any image format that Pillow can decode (JPEG, PNG, WebP, GIF,
    BMP, TIFF, …). See :func:`convert_image` for parameter details.
    """
    image = _open_as_rgb(image_data)
    return _process(image, width, height, rotation, locked)


def _process(
    image: "Image.Image",
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> bytes:
    """Shared implementation used by both public entry points."""
    if not locked:
        # The Fraimic way: a mismatched image lies sideways at full size.
        image = _auto_rotate(image, width, height)
    # Locked: no source rotation -- the centered cover-crop below trims a
    # mismatched image to the target shape while keeping it upright.
    image = _resize_cover_centered(image, width, height)
    if rotation:
        image = image.rotate(rotation, expand=True)
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image)


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
) -> bytes:
    """
    Convert raw image bytes to Spectra 6 binary using a manually-chosen crop
    rectangle instead of the automatic letterbox path. See
    :func:`convert_image_cropped` for parameter details.
    """
    image = _open_as_rgb(image_data)
    return _process_cropped(image, width, height, crop_box, rotation)


def _process_cropped(
    image: "Image.Image",
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
) -> bytes:
    """Shared implementation for the manual-crop public entry points.

    No auto-rotate step here -- unlike the letterbox path, the crop box's
    position and aspect ratio already fully encode the user's chosen
    orientation, so rotating the source image first would only make the
    saved (normalized) crop coordinates harder to reason about.
    """
    image = _crop_to_box(image, crop_box)
    image = image.resize((width, height), Image.LANCZOS)
    if rotation:
        image = image.rotate(rotation, expand=True)
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image)
