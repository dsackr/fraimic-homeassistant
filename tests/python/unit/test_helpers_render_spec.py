"""render_spec_for_entry: orientation lock + rotation + hanging-edge
resolution (KPF 22).

Flagged as the single riskiest piece of logic in the codebase -- a wrong
rotation here means every image sent from every path lands sideways or
upside-down on the physical frame, and it's invisible until someone looks
at hardware. Pure dataclass logic, no HA dependency.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.fraimic.const import (
    CONF_HEIGHT,
    CONF_ORIENTATION,
    CONF_ROTATE_LANDSCAPE_180,
    CONF_ROTATE_PORTRAIT_180,
    CONF_ROTATION_EDGE,
    CONF_WIDTH,
    EDGE_LEFT,
    EDGE_RIGHT,
    ORIENTATION_AUTO,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from custom_components.fraimic.helpers import render_spec_for_entry


def _entry(width: int, height: int, **options) -> SimpleNamespace:
    """A minimal stand-in for ConfigEntry -- render_spec_for_entry only
    reads entry.data[...] and entry.options.get(...)."""
    return SimpleNamespace(
        data={CONF_WIDTH: width, CONF_HEIGHT: height},
        options=options,
    )


def test_auto_orientation_native_dimensions_unchanged_no_rotation():
    spec = render_spec_for_entry(_entry(1200, 1600))
    assert (spec.width, spec.height) == (1200, 1600)
    assert spec.rotation == 0
    assert spec.locked is False


def test_locked_portrait_on_landscape_native_rotates_90_left_edge():
    # Landscape-native panel (2560x1440), user locks portrait -> compose
    # portrait then rotate 90 CCW back onto the native landscape buffer.
    spec = render_spec_for_entry(
        _entry(2560, 1440, **{CONF_ORIENTATION: ORIENTATION_PORTRAIT})
    )
    assert (spec.width, spec.height) == (1440, 2560)
    assert spec.rotation == 90
    assert spec.locked is True


def test_locked_portrait_on_landscape_native_rotates_270_right_edge():
    spec = render_spec_for_entry(
        _entry(
            2560,
            1440,
            **{
                CONF_ORIENTATION: ORIENTATION_PORTRAIT,
                CONF_ROTATION_EDGE: EDGE_RIGHT,
            },
        )
    )
    assert spec.rotation == 270


def test_locked_landscape_on_portrait_native_rotates():
    spec = render_spec_for_entry(
        _entry(1200, 1600, **{CONF_ORIENTATION: ORIENTATION_LANDSCAPE})
    )
    assert (spec.width, spec.height) == (1600, 1200)
    assert spec.rotation == 90
    assert spec.locked is True


def test_locked_orientation_matching_native_no_rotation():
    # Portrait-native panel, locked to portrait -- already matches, no
    # rotation needed even though locked is True.
    spec = render_spec_for_entry(
        _entry(1200, 1600, **{CONF_ORIENTATION: ORIENTATION_PORTRAIT})
    )
    assert (spec.width, spec.height) == (1200, 1600)
    assert spec.rotation == 0
    assert spec.locked is True


def test_unlocked_mismatch_no_lock_branch_touched():
    spec = render_spec_for_entry(_entry(1200, 1600, **{CONF_ORIENTATION: ORIENTATION_AUTO}))
    assert spec.locked is False
    assert spec.rotation == 0


@pytest.mark.parametrize(
    ("width", "height", "flag_key"),
    [
        (2560, 1440, CONF_ROTATE_LANDSCAPE_180),  # native landscape, unlocked
        (1200, 1600, CONF_ROTATE_PORTRAIT_180),  # native portrait, unlocked
    ],
)
def test_180_flip_composes_with_no_lock(width, height, flag_key):
    spec = render_spec_for_entry(_entry(width, height, **{flag_key: True}))
    assert spec.rotation == 180


def test_180_flip_composes_with_lock_rotation():
    # Locked portrait on landscape-native gives rotation=90; landscape-180
    # flag keys off the *effective* (post-lock) orientation, which is
    # portrait here, so CONF_ROTATE_LANDSCAPE_180 must NOT apply -- only
    # CONF_ROTATE_PORTRAIT_180 composes with the lock's 90.
    spec = render_spec_for_entry(
        _entry(
            2560,
            1440,
            **{
                CONF_ORIENTATION: ORIENTATION_PORTRAIT,
                CONF_ROTATE_PORTRAIT_180: True,
            },
        )
    )
    assert spec.rotation == (90 + 180) % 360
    assert spec.locked is True


def test_variant_cache_key_distinguishes_rotation_and_lock_combinations():
    plain = render_spec_for_entry(_entry(1200, 1600))
    rotated = render_spec_for_entry(_entry(1200, 1600, **{CONF_ROTATE_PORTRAIT_180: True}))
    locked = render_spec_for_entry(_entry(1200, 1600, **{CONF_ORIENTATION: ORIENTATION_PORTRAIT}))
    locked_rotated = render_spec_for_entry(
        _entry(
            2560,
            1440,
            **{CONF_ORIENTATION: ORIENTATION_PORTRAIT, CONF_ROTATE_PORTRAIT_180: True},
        )
    )

    variants = {plain.variant, rotated.variant, locked.variant, locked_rotated.variant}
    assert plain.variant == ""
    assert len(variants) == 4, "each distinct combination must produce a distinct cache key"
