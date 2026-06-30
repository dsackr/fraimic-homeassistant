"""
Spectra 6 image converter for Fraimic e-ink frame.

Converts arbitrary images (any format Pillow supports) to the raw binary format
expected by the Fraimic API for its E Ink Spectra 6 display.

Binary format specification
----------------------------
- 4 bits per pixel (one nibble)
- 2 pixels packed per byte: high nibble = pixel at even x, low nibble = pixel at odd x
- Pixels are written in reverse scan order: y from bottom to top, x from right to left
- Nibble values map to Spectra 6 colors (note: value 4 is unused by the hardware):
    0 = Black
    1 = White
    2 = Yellow
    3 = Red
    5 = Blue
    6 = Green

Conversion pipeline
--------------------
1. Open image (any format Pillow supports)
2. Auto-rotate to match target orientation (landscape vs portrait) if needed
3. Resize to fit target dimensions while preserving aspect ratio; letterbox with white fill
4. Quantize to the 6 Spectra 6 real-world colors using Floyd-Steinberg dithering
5. Remap pixels to compensate for the frame's dual-half-panel hardware addressing
   (see _remap_for_dual_panel_hardware for details)
6. Pack pixels into the nibble format described above

Hardware quirk: dual half-panel addressing
-------------------------------------------
The physical display is built from two side-by-side half-width e-ink panels
(each width // 2 wide). The firmware does not address the incoming byte
buffer as a single `width` x `height` raster -- it reinterprets the exact
same bytes as a (width // 2) x (height * 2) raster (using the same
bottom-to-top / right-to-left scan convention used to pack them), then
splits that taller, narrower raster in half: the first `height` rows go to
the RIGHT physical panel (flipped vertically), and the remaining `height`
rows go to the LEFT physical panel (flipped vertically).

Without compensating for this, a normally-packed image displays as two
scrambled, vertically-flipped, left/right-swapped halves. We compensate by
pre-scrambling pixels (_remap_for_dual_panel_hardware) before packing, so
that after the firmware applies its own (fixed) reinterpretation, the
visible result matches the original image.
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


def _resize_with_letterbox(
    image: "Image.Image",
    target_width: int,
    target_height: int,
) -> "Image.Image":
    """
    Resize *image* to fit within *target_width* × *target_height* while
    preserving the original aspect ratio. Any uncovered area is filled with
    white (matching the default Spectra 6 background).

    The image is scaled so that it fills the longest dimension, then centred.
    This means no content is cropped, but narrow images may have white bars on
    the sides (letterbox / pillarbox).
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


def _remap_for_dual_panel_hardware(image: "Image.Image") -> "Image.Image":
    """
    Pre-scramble pixels to compensate for the frame's dual half-panel
    hardware addressing (see module docstring for the full explanation).

    The firmware reinterprets the packed byte buffer as a
    (width // 2) x (height * 2) raster using the same scan convention used
    to pack it, then shows the first `height` rows of that raster (flipped
    vertically) on the RIGHT physical panel and the remaining `height` rows
    (flipped vertically) on the LEFT physical panel.

    This function computes, for every source pixel, where it will actually
    end up once the firmware applies that transform, and places the desired
    final pixel there instead -- so the *displayed* result matches the
    input image once it passes through the firmware's transform.

    :param image: RGB image already quantized to the Spectra 6 palette.
    :returns: A new RGB image of the same size, with pixels rearranged so
        that packing and sending it produces a correct on-frame display.
    """
    width, height = image.size
    half_width = width // 2
    src_pixels = image.load()

    remapped = Image.new("RGB", (width, height))
    dst_pixels = remapped.load()

    for y in range(height):
        for x in range(width):
            if x < half_width:
                strip_x, strip_y = x, 2 * y
            else:
                strip_x, strip_y = x - half_width, 2 * y + 1

            if strip_y < height:
                # Lands in the firmware's first half-raster -> RIGHT panel.
                panel_is_right = True
                y_within_half = strip_y
            else:
                # Lands in the firmware's second half-raster -> LEFT panel.
                panel_is_right = False
                y_within_half = strip_y - height

            # The firmware flips each half vertically before displaying it.
            final_y = (height - 1) - y_within_half
            final_x = strip_x + half_width if panel_is_right else strip_x

            dst_pixels[x, y] = src_pixels[final_x, final_y]

    return remapped


def _pack_to_spectra6_bin(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized RGB image into the raw Spectra 6 binary format.

    Scan order: y from *bottom* to *top*; within each row, columns are
    grouped into (even_x, odd_x) pairs and those pairs are emitted from
    right to left. High nibble = pixel at even x, low nibble = pixel at
    odd x — this pairing is fixed regardless of image width, so it stays
    correct whether the width is even or odd (previous nibble-by-nibble
    parity tracking broke for even widths, since the first column visited
    in reverse order is then odd, not even).

    :param quantized_image: RGB image whose pixels are restricted to the six
        entries of :data:`SPECTRA6_REAL_WORLD_RGB`.
    :returns: Raw bytes ready to be sent as a ``.bin`` file.
    :raises ValueError: If a pixel colour does not match any palette entry
        (indicates a bug in the quantization step).
    """
    raw: bytearray = bytearray()
    width = quantized_image.width

    for y in reversed(range(quantized_image.height)):
        for even_x in reversed(range(0, width, 2)):
            high_nibble = _nibble_for_pixel(quantized_image, even_x, y)
            odd_x = even_x + 1
            if odd_x < width:
                low_nibble = _nibble_for_pixel(quantized_image, odd_x, y)
            else:
                # Odd total width — pad the missing partner pixel with white.
                low_nibble = SPECTRA6_NIBBLE_VALUES[
                    SPECTRA6_REAL_WORLD_RGB.index((232, 232, 232))
                ]
            raw.append((high_nibble << 4) | low_nibble)

    return bytes(raw)


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

def convert_image(image_path: str, width: int, height: int) -> bytes:
    """
    Convert an image file to the raw Spectra 6 binary format.

    The full conversion pipeline is:

    1. Open the image (any format Pillow supports; EXIF orientation applied).
    2. Auto-rotate 270° if the image and target have mismatched orientations.
    3. Resize / letterbox to *width* × *height* with a white background.
    4. Quantize to the 6 Spectra 6 palette colours with Floyd-Steinberg
       dithering.
    5. Pack pixels into 4-bit nibbles in reverse scan order.

    :param image_path: Path to the source image file.
    :param width: Target display width in pixels.
    :param height: Target display height in pixels.
    :returns: Raw bytes in Spectra 6 ``.bin`` format, ready for the Fraimic
        API.  The length will be ``(width * height) // 2`` bytes.
    :raises FileNotFoundError: If *image_path* does not exist.
    :raises ImportError: If Pillow is not installed.
    """
    image = _open_as_rgb(image_path)
    return _process(image, width, height)


def convert_image_bytes(image_data: bytes, width: int, height: int) -> bytes:
    """
    Convert raw image bytes to the raw Spectra 6 binary format.

    Accepts any image format that Pillow can decode (JPEG, PNG, WebP, GIF,
    BMP, TIFF, …).

    :param image_data: Raw bytes of the source image file.
    :param width: Target display width in pixels.
    :param height: Target display height in pixels.
    :returns: Raw bytes in Spectra 6 ``.bin`` format, ready for the Fraimic
        API.  The length will be ``(width * height) // 2`` bytes.
    :raises ImportError: If Pillow is not installed.
    :raises PIL.UnidentifiedImageError: If *image_data* is not a recognised
        image format.
    """
    image = _open_as_rgb(image_data)
    return _process(image, width, height)


def _process(image: "Image.Image", width: int, height: int) -> bytes:
    """Shared implementation used by both public entry points."""
    image = _auto_rotate(image, width, height)
    image = _resize_with_letterbox(image, width, height)
    image = _quantize_to_spectra6(image)
    image = _remap_for_dual_panel_hardware(image)
    return _pack_to_spectra6_bin(image)
