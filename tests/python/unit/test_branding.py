"""Product branding + domain identity (KPF 34)."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.digital_frames.const import (
    DOMAIN,
    LEGACY_DOMAIN,
    LIBRARY_DIRNAME,
    PRODUCT_NAME,
)

ROOT = Path(__file__).resolve().parents[3]


def test_product_name_constant():
    assert PRODUCT_NAME == "Digital Frames"
    assert DOMAIN == "digital_frames"
    assert LEGACY_DOMAIN == "fraimic"


def test_library_dirname_stable_for_albums():
    """Albums live under the legacy path so domain renames do not orphan them."""
    assert LIBRARY_DIRNAME == "fraimic_library"


def test_manifest_display_name_and_domain():
    data = json.loads(
        (ROOT / "custom_components/digital_frames/manifest.json").read_text()
    )
    assert data["name"] == "Digital Frames"
    assert data["domain"] == "digital_frames"


def test_hacs_display_name():
    data = json.loads((ROOT / "hacs.json").read_text())
    assert data["name"] == "Digital Frames"


def test_library_settings_keys_for_migration():
    from custom_components.digital_frames import library as lib

    assert lib._SETTINGS_STORAGE_KEY == "digital_frames_library_settings"
    assert lib._LEGACY_SETTINGS_STORAGE_KEY == "fraimic_library_settings"


def test_panel_paths_primary_and_legacy_constant():
    """Primary path is digital_frames; code also aliases /fraimic for bookmarks."""
    import importlib

    init_mod = importlib.import_module("custom_components.digital_frames")
    assert init_mod._PANEL_PATH == "digital_frames"
    assert init_mod._PANEL_URL.startswith("/digital_frames/")
