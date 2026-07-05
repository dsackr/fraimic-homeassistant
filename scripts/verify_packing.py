#!/usr/bin/env python3
"""Byte-identity verification for image_converter's two packing paths.

The "fast" packer (pack_method="fast", see image_converter._pack_p_image_fast)
must produce exactly the same .bin bytes as the legacy per-pixel path for
every registered frame resolution and both byte layouts -- a mismatch doesn't
error on the frame, it silently garbles the displayed image. Run this after
touching either path:

    python3 scripts/verify_packing.py

Optionally pass image files to also verify against real photos:

    python3 scripts/verify_packing.py ~/Pictures/foo.jpg ~/Pictures/bar.png

Exits non-zero on any mismatch.
"""

from __future__ import annotations

import importlib.util
import io
import random
import sys
import time
import types
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required: pip install Pillow")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "fraimic"


def _load_component_modules():
    """Load frame_types + image_converter as a synthetic package so their
    relative imports work without pulling in Home Assistant dependencies
    from the integration's __init__.py."""
    pkg = types.ModuleType("fraimic_verify")
    pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["fraimic_verify"] = pkg
    for name in ("frame_types", "image_converter"):
        spec = importlib.util.spec_from_file_location(
            f"fraimic_verify.{name}", COMPONENT_DIR / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"fraimic_verify.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["fraimic_verify.frame_types"], sys.modules["fraimic_verify.image_converter"]


def _test_images(width: int, height: int) -> "list[tuple[str, Image.Image]]":
    """A spread of source content: dithered noise (worst case for packing
    bugs), gradients (exercises all palette colours via error diffusion),
    solid colours (degenerate case), and a photo-ish synthetic."""
    rng = random.Random(1234)
    images = []

    noise = Image.new("RGB", (width, height))
    noise.putdata([
        (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        for _ in range(width * height)
    ])
    images.append(("random noise", noise))

    gradient = Image.new("RGB", (width, height))
    gradient.putdata([
        (int(255 * x / width), int(255 * y / height), int(255 * (x + y) / (width + height)))
        for y in range(height) for x in range(width)
    ])
    images.append(("rgb gradient", gradient))

    images.append(("solid white", Image.new("RGB", (width, height), (255, 255, 255))))
    images.append(("solid red", Image.new("RGB", (width, height), (178, 19, 24))))

    blocks = Image.new("RGB", (width, height))
    blocks.putdata([
        ((x * 7 // max(1, width)) * 40 % 256,
         (y * 5 // max(1, height)) * 55 % 256,
         (x ^ y) & 0xFF)
        for y in range(height) for x in range(width)
    ])
    images.append(("xor blocks", blocks))

    return images


def main() -> int:
    frame_types, ic = _load_component_modules()

    failures = 0
    checks = 0
    legacy_total = 0.0
    fast_total = 0.0

    # Every registered panel resolution (deduped), both orientations.
    resolutions = set()
    for ft in frame_types.FRAME_TYPES.values():
        w, h = ft.resolution
        resolutions.add((w, h))
        resolutions.add((h, w))

    for (width, height) in sorted(resolutions):
        layout = frame_types.byte_layout_for_resolution(width, height)
        for label, img in _test_images(width, height):
            # Quantize once so both packers pack the exact same pixels --
            # this isolates the packing step, which is what changed.
            p_img = ic._quantize_to_spectra6_p(img)
            rgb_img = p_img.convert("RGB")  # what the legacy packer consumes

            t0 = time.perf_counter()
            legacy = ic._pack_to_spectra6_bin(rgb_img)
            t1 = time.perf_counter()
            fast = ic._pack_p_image_fast(p_img)
            t2 = time.perf_counter()
            legacy_total += t1 - t0
            fast_total += t2 - t1

            checks += 1
            expected_len = (width * height) // 2
            ok = legacy == fast and len(legacy) == expected_len
            status = "OK " if ok else "FAIL"
            if not ok:
                failures += 1
                first_diff = next(
                    (i for i, (a, b) in enumerate(zip(legacy, fast)) if a != b),
                    min(len(legacy), len(fast)),
                )
                print(f"[{status}] {width}x{height} ({layout}) {label}: "
                      f"len {len(legacy)} vs {len(fast)}, first diff at byte {first_diff}")
            else:
                print(f"[{status}] {width}x{height} ({layout}) {label}: "
                      f"{len(legacy)} bytes, legacy {t1 - t0:.2f}s / fast {t2 - t1:.3f}s")

    # Odd-width edge cases exercise the white-padding branch that no
    # registered resolution hits today. The layout registry rejects
    # unregistered resolutions, so call the two layout packers directly.
    for (width, height) in ((37, 12), (101, 7)):
        for label, img in _test_images(width, height)[:2]:
            p_img = ic._quantize_to_spectra6_p(img)
            rgb_img = p_img.convert("RGB")
            nib = p_img.tobytes().translate(ic._P_INDEX_TO_NIBBLE)
            half = width // 2

            legacy_split = ic._pack_split_halves(rgb_img)
            fast_split = (
                ic._pack_segments_fast(nib, width, height, 0, half)
                + ic._pack_segments_fast(nib, width, height, half, width)
            )
            legacy_seq = ic._pack_sequential(rgb_img)
            fast_seq = ic._pack_segments_fast(nib, width, height, 0, width)

            for layout_label, a, b in (
                ("split_half", legacy_split, fast_split),
                ("sequential", legacy_seq, fast_seq),
            ):
                checks += 1
                if a != b:
                    failures += 1
                    print(f"[FAIL] odd {width}x{height} ({layout_label}) {label}: mismatch")
                else:
                    print(f"[OK ] odd {width}x{height} ({layout_label}) {label}: {len(a)} bytes")

    # Real photos passed on the command line: run the FULL public pipeline
    # both ways (auto-rotate + cover-crop + quantize + pack) at every
    # registered resolution.
    for arg in sys.argv[1:]:
        raw = Path(arg).read_bytes()
        for (width, height) in sorted({ft.resolution for ft in frame_types.FRAME_TYPES.values()}):
            legacy = ic.convert_image_bytes(raw, width, height)
            fast = ic.convert_image_bytes(raw, width, height, pack_method="fast")
            checks += 1
            if legacy != fast:
                failures += 1
                print(f"[FAIL] {arg} @ {width}x{height}: full-pipeline mismatch")
            else:
                print(f"[OK ] {arg} @ {width}x{height}: full pipeline identical ({len(legacy)} bytes)")

    print()
    print(f"{checks} checks, {failures} failures")
    if legacy_total:
        print(f"packing time (summed over checks): legacy {legacy_total:.2f}s, "
              f"fast {fast_total:.3f}s ({legacy_total / max(fast_total, 1e-9):.0f}x faster)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
