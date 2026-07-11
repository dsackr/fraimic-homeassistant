"""Frame-type registry & byte-layout dispatch (KPF 23).

Garbles the displayed image on an unregistered/misregistered panel size --
same failure mode as image_converter, one layer up. Pure logic, no HA
dependency.
"""

from __future__ import annotations

import pytest

from custom_components.fraimic.frame_types import (
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
    byte_layout_for_resolution,
)


def test_every_registered_resolution_resolves_to_its_declared_layout():
    for frame_type in FRAME_TYPES.values():
        width, height = frame_type.resolution
        assert byte_layout_for_resolution(width, height) == frame_type.byte_layout


def test_unknown_resolution_raises():
    with pytest.raises(ValueError, match="No registered frame type"):
        byte_layout_for_resolution(9999, 9999)


def test_orientation_swapped_dimensions_still_resolve():
    # Some frames report swapped (h, w) after a physical rotation; the
    # coordinator persists whatever's reported, so lookup must be
    # orientation-agnostic (see byte_layout_for_resolution's docstring).
    for frame_type in FRAME_TYPES.values():
        width, height = frame_type.resolution
        assert byte_layout_for_resolution(height, width) == frame_type.byte_layout


def test_known_layouts_are_represented():
    layouts = {ft.byte_layout for ft in FRAME_TYPES.values()}
    assert LAYOUT_SPLIT_HALF in layouts
    assert LAYOUT_SEQUENTIAL in layouts
