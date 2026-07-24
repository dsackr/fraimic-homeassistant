"""PanelCodec: explicit encode boundary for frame wire payloads.

Phase 1 FramePort seam (see docs/FRAME_PORT.md):

- **Core** decides which image goes to which frame and at what geometry.
- **PanelCodec** turns source pixels into wire payload bytes (Spectra 6
  split-half / sequential, or JPEG for Meural).
- **Transport** (coordinator) delivers those bytes and applies sleep-queue /
  timeout policy from the panel profile.

Library backfill and on-demand send encoding should call
:func:`encode_for_panel` rather than importing ``image_converter`` directly,
so there is one named place where codec selection is owned.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .const import (
    CONF_DRIVER,
    DRIVER_MEURAL,
    DRIVER_SAMSUNG,
    MEURAL_SIZE_LABEL,
    SAMSUNG_SIZE_LABEL,
)
from .frame_types import (
    CODEC_SPECTRA6_SEQUENTIAL,
    CODEC_SPECTRA6_SPLIT_HALF,
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
    codec_id_for_resolution,
    frame_type_for_resolution,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

# Full-color JPEG payload for Meural local postcard (and future RGB frames).
CODEC_JPEG_Q90 = "jpeg_q90"
# Full-color PNG for Samsung EM32DX MDC content-download (Joyous protocol).
CODEC_PNG = "png"
LAYOUT_NONE = "none"


@dataclass(frozen=True)
class PanelCodec:
    """How pixels become wire bytes for one panel family."""

    id: str
    byte_layout: str  # LAYOUT_* — Spectra packers; LAYOUT_NONE for JPEG
    color_mode: str = "spectra6"
    preferred_payload: str = "spectra6_bin"


# Registry of codecs this integration can produce.
CODECS: dict[str, PanelCodec] = {
    CODEC_SPECTRA6_SPLIT_HALF: PanelCodec(
        id=CODEC_SPECTRA6_SPLIT_HALF,
        byte_layout=LAYOUT_SPLIT_HALF,
    ),
    CODEC_SPECTRA6_SEQUENTIAL: PanelCodec(
        id=CODEC_SPECTRA6_SEQUENTIAL,
        byte_layout=LAYOUT_SEQUENTIAL,
    ),
    CODEC_JPEG_Q90: PanelCodec(
        id=CODEC_JPEG_Q90,
        byte_layout=LAYOUT_NONE,
        color_mode="rgb",
        preferred_payload="jpeg",
    ),
    CODEC_PNG: PanelCodec(
        id=CODEC_PNG,
        byte_layout=LAYOUT_NONE,
        color_mode="rgb",
        preferred_payload="png",
    ),
}


def panel_codec_for_id(codec_id: str) -> PanelCodec:
    """Look up a codec by stable id."""
    try:
        return CODECS[codec_id]
    except KeyError as err:
        raise ValueError(f"Unknown panel codec id {codec_id!r}") from err


def panel_codec_for_resolution(width: int, height: int) -> PanelCodec:
    """Resolve codec from Spectra panel resolution (orientation-agnostic)."""
    return panel_codec_for_id(codec_id_for_resolution(width, height))


def panel_codec_for_frame_type_id(size: str) -> PanelCodec:
    """Resolve codec from CONF_SIZE / FRAME_TYPES id (e.g. \"7.3\")."""
    try:
        frame_type = FRAME_TYPES[size]
    except KeyError as err:
        raise ValueError(f"Unknown frame type id {size!r}") from err
    return panel_codec_for_id(frame_type.codec_id)


def panel_codec_for_entry(entry: "ConfigEntry") -> PanelCodec:
    """Resolve codec for a config entry (driver, then size, then geometry)."""
    if entry.data.get(CONF_DRIVER) == DRIVER_MEURAL:
        return panel_codec_for_id(CODEC_JPEG_Q90)
    if entry.data.get(CONF_DRIVER) == DRIVER_SAMSUNG:
        return panel_codec_for_id(CODEC_PNG)

    size = entry.data.get("size")
    if isinstance(size, str) and size == MEURAL_SIZE_LABEL:
        return panel_codec_for_id(CODEC_JPEG_Q90)
    if isinstance(size, str) and size == SAMSUNG_SIZE_LABEL:
        return panel_codec_for_id(CODEC_PNG)
    if isinstance(size, str) and size in FRAME_TYPES:
        return panel_codec_for_frame_type_id(size)

    width = entry.data.get("width")
    height = entry.data.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return panel_codec_for_resolution(width, height)

    raise ValueError(
        f"Config entry {entry.entry_id} has no size or dimensions to resolve a panel codec"
    )


def byte_layout_for_codec(codec: PanelCodec | str) -> str:
    """Layout name for packers / skill renderer config.json."""
    if isinstance(codec, PanelCodec):
        return codec.byte_layout
    return panel_codec_for_id(codec).byte_layout


def _compose_rgb(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
):
    from .image_converter import (  # noqa: PLC0415
        _auto_rotate,
        _open_as_rgb,
        _resize_cover_centered,
    )
    from PIL import Image as PILImage  # noqa: PLC0415

    image = _open_as_rgb(source_bytes)
    if crop_box is not None:
        x0, y0, x1, y1 = [float(v) for v in crop_box]
        w, h = image.size
        box = (
            int(round(x0 * w)),
            int(round(y0 * h)),
            int(round(x1 * w)),
            int(round(y1 * h)),
        )
        image = image.crop(box)
        image = image.resize((width, height), PILImage.LANCZOS)
    else:
        if not locked:
            image = _auto_rotate(image, width, height)
        image = _resize_cover_centered(image, width, height)
    if rotation:
        image = image.rotate(rotation, expand=True)
        if image.size != (width, height):
            image = image.resize((width, height), PILImage.LANCZOS)
    return image


def _encode_jpeg_bytes(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
    quality: int = 90,
) -> bytes:
    """Compose *source_bytes* to *width*×*height* and encode JPEG."""
    image = _compose_rgb(source_bytes, width, height, rotation, locked, crop_box)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _encode_png_bytes(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
) -> bytes:
    """Compose *source_bytes* to *width*×*height* and encode PNG."""
    image = _compose_rgb(source_bytes, width, height, rotation, locked, crop_box)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def encode_for_panel(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
    codec_id: str | None = None,
) -> bytes:
    """Encode a source image into wire payload for a panel.

    *codec_id* selects Spectra vs JPEG. When omitted, resolved from
    resolution via the Fraimic FRAME_TYPES registry (Spectra panels only).

    Positional-friendly signature so callers can pass this to
    ``hass.async_add_executor_job`` without kwargs (except trailing
    *codec_id* should be passed positionally when using the executor with
    all args).
    """
    if codec_id is None:
        # Spectra path: require a registered frame type at this geometry.
        _ = frame_type_for_resolution(width, height)
        codec_id = codec_id_for_resolution(width, height)

    if codec_id == CODEC_JPEG_Q90:
        return _encode_jpeg_bytes(
            source_bytes,
            width,
            height,
            rotation,
            locked,
            crop_box,
            quality=90,
        )
    if codec_id == CODEC_PNG:
        return _encode_png_bytes(
            source_bytes,
            width,
            height,
            rotation,
            locked,
            crop_box,
        )

    # Spectra 6 packing — layout from registered frame type.
    _ = frame_type_for_resolution(width, height)

    from .image_converter import (  # noqa: PLC0415
        convert_image_bytes,
        convert_image_bytes_cropped,
    )

    if crop_box is not None:
        return convert_image_bytes_cropped(
            source_bytes,
            width,
            height,
            tuple(crop_box),
            rotation,
            pack_method,
        )
    return convert_image_bytes(
        source_bytes,
        width,
        height,
        rotation,
        locked,
        pack_method,
    )


def encode_for_panel_with_preview(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    codec_id: str | None = None,
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
) -> tuple[bytes, bytes]:
    """Like :func:`encode_for_panel`, plus a small PNG of the composed image.

    *crop_box* (normalized (x0, y0, x1, y1), same semantics as
    :func:`encode_for_panel`) is used by wall-banner message sends, where
    each frame's crop into the shared composed canvas is the only thing
    that differs between otherwise-identical calls.
    """
    if codec_id is None:
        _ = frame_type_for_resolution(width, height)
        codec_id = codec_id_for_resolution(width, height)

    if codec_id in (CODEC_JPEG_Q90, CODEC_PNG):
        from .image_converter import _encode_preview_png  # noqa: PLC0415

        image = _compose_rgb(source_bytes, width, height, rotation, locked, crop_box)
        if codec_id == CODEC_JPEG_Q90:
            wire = _encode_jpeg_bytes(
                source_bytes, width, height, rotation, locked, crop_box, 90
            )
        else:
            wire = _encode_png_bytes(
                source_bytes, width, height, rotation, locked, crop_box
            )
        return wire, _encode_preview_png(image)

    if crop_box is not None:
        from .image_converter import (  # noqa: PLC0415
            convert_image_bytes_cropped_with_preview,
        )

        return convert_image_bytes_cropped_with_preview(
            source_bytes, width, height, tuple(crop_box), rotation
        )

    from .image_converter import convert_image_bytes_with_preview  # noqa: PLC0415

    return convert_image_bytes_with_preview(
        source_bytes, width, height, rotation, locked
    )


def encode_path_for_panel_with_preview(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    codec_id: str | None = None,
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
) -> tuple[bytes, bytes]:
    """Encode a filesystem path for the panel, with preview PNG."""
    with open(image_path, "rb") as f:
        raw = f.read()
    return encode_for_panel_with_preview(
        raw, width, height, rotation, locked, codec_id, crop_box
    )


def text_skill_payload_for_codec(
    spectra_bin: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    codec_id: str | None = None,
    rgb_png: bytes | None = None,
) -> tuple[bytes, bytes | None]:
    """Turn text-skill renderer outputs into wire bytes + preview for *codec_id*.

    The pinned xOTD renderer writes:

    - ``xotd.bin`` — Spectra 6 packed (Fraimic wire)
    - ``xotd_preview.png`` — full RGB composition *before* packing (fonts may
      anti-alias; palette colors are intentional, intermediate AA grays are
      not)

    Prefer *rgb_png* when present:

    - **JPEG panels (Meural):** encode JPEG from the RGB PNG (not unpack of
      ``.bin``), so anti-aliased text is not posterized through Spectra 6.
    - **PNG panels (Samsung):** encode PNG from the RGB PNG the same way.
    - **Spectra panels:** wire stays ``.bin``; preview prefers RGB PNG for a
      sharper last-image thumbnail.

    Fallback when *rgb_png* is missing: Spectra pass-through + unpack-based
    preview; JPEG/PNG unpack ``.bin`` (6-color posterized).

    *width*/*height* are the renderer's *composition* canvas -- the frame's
    effective (possibly orientation-swapped) size, per
    ``helpers.render_spec_for_entry``. When *rotation* is nonzero (the
    frame's orientation lock disagrees with its native buffer), the Spectra
    branch below must rotate + repack before returning, exactly like
    ``image_converter._process`` does for ordinary photo sends -- otherwise
    the wire bytes stay packed at the composition size while the panel's
    raster expects its native (post-rotation) size, producing a silently
    sideways/garbled render with no exception (see KEY_PRODUCT_FLOWS.md
    KPF 28/22).

    Positional-friendly for ``async_add_executor_job``.
    """
    from .image_converter import (  # noqa: PLC0415
        _encode_preview_png,
        _open_as_rgb,
        _pack_p_image_fast,
        _quantize_to_spectra6_p,
        preview_png_from_bin,
        unpack_spectra6_bin,
    )

    def _image_from_rgb_png() -> Any:
        image = _open_as_rgb(rgb_png)  # type: ignore[arg-type]
        if rotation:
            image = image.rotate(rotation, expand=True)
        return image

    def _decode_and_rotate() -> Any:
        """Decode the source image and apply *rotation*, preferring
        *rgb_png* when present -- the shared "unpack, then conditionally
        rotate" step both the JPEG/PNG branch and the Spectra rotate branch
        below need."""
        if rgb_png:
            return _image_from_rgb_png()
        image = unpack_spectra6_bin(spectra_bin, width, height)
        if rotation:
            image = image.rotate(rotation, expand=True)
        return image

    if codec_id in (CODEC_JPEG_Q90, CODEC_PNG):
        image = _decode_and_rotate()
        buf = io.BytesIO()
        if codec_id == CODEC_JPEG_Q90:
            image.save(buf, format="JPEG", quality=90, optimize=True)
        else:
            image.save(buf, format="PNG")
        return buf.getvalue(), _encode_preview_png(image)

    # Spectra wire payload. If the panel's native buffer disagrees with the
    # composition canvas, rotate to native orientation and repack -- reusing
    # whichever source image we already decoded for both the repack and the
    # preview so a rotated frame's preview always matches what was sent.
    rotated_image: Any | None = None
    if rotation:
        rotated_image = _decode_and_rotate()
        p_image = _quantize_to_spectra6_p(rotated_image)
        spectra_bin = _pack_p_image_fast(p_image)

    preview: bytes | None = None
    if rotated_image is not None:
        # spectra_bin is now packed at the rotated (native) size, not
        # width x height -- the preview_png_from_bin fallback below assumes
        # its bin matches width x height, so it must not be used here.
        try:
            preview = _encode_preview_png(rotated_image)
        except Exception:  # noqa: BLE001
            preview = None
        return spectra_bin, preview
    if rgb_png:
        try:
            preview = _encode_preview_png(_image_from_rgb_png())
        except Exception:  # noqa: BLE001
            preview = None
    if preview is None:
        try:
            preview = preview_png_from_bin(spectra_bin, width, height)
        except Exception:  # noqa: BLE001
            preview = None
    return spectra_bin, preview
