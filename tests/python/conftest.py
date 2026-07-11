"""Shared fixtures for the fraimic backend test suite.

Uses pytest-homeassistant-custom-component (PHACC), which vendors a real
Home Assistant core and provides the `hass` fixture, MockConfigEntry,
aioclient_mock, and custom-component loading. Fixtures here wrap those
primitives with this integration's actual config-entry shape (see
const.py) so individual test files don't each re-derive it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# custom_components/fraimic imports its sibling modules as `from .const import
# ...` -- PHACC's enable_custom_integrations fixture makes HA's component
# loader look under this repo's custom_components/ for the "fraimic" domain,
# but the repo root also needs to be on sys.path for that discovery to work
# when pytest's rootdir isn't already there.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force our custom_components.fraimic to be the first thing bound into
# sys.modules for the "custom_components" top-level name. PHACC ships its
# own custom_components/__init__.py (a *regular* package, used by HA core's
# own test suite) under its installed package dir; if hass-fixture setup
# imports that one first (which it does, as soon as any test lazily
# `import`s custom_components.fraimic *after* the hass fixture has already
# run), sys.modules["custom_components"] gets cached pointing at PHACC's
# directory and every subsequent `custom_components.fraimic` import fails
# with ModuleNotFoundError, no matter what's on sys.path. Importing eagerly
# here, at conftest collection time (before any fixture runs), wins that
# race for our own package instead.
import custom_components.fraimic  # noqa: E402,F401


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make hass.config_entries.async_setup discover custom_components/fraimic."""
    yield


@pytest.fixture
def make_frame_entry():
    """Factory for a frame config entry using this integration's real data/
    options schema (const.py's CONF_* keys), with sane defaults so most
    tests only need to override the fields they care about."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.fraimic.const import (
        CONF_DEVICE_KEY,
        CONF_HEIGHT,
        CONF_HOST,
        CONF_MAC,
        CONF_NAME,
        CONF_SIZE,
        CONF_WIDTH,
        DOMAIN,
    )

    def _make(
        *,
        host: str = "192.168.1.50",
        name: str = "Living Room Frame",
        width: int = 1200,
        height: int = 1600,
        size: str = "13.3",
        device_key: str = "fraimic-device-key-1",
        mac: str = "aabbccddeeff",
        options: dict | None = None,
        entry_id: str | None = None,
    ):
        data = {
            CONF_HOST: host,
            CONF_NAME: name,
            CONF_WIDTH: width,
            CONF_HEIGHT: height,
            CONF_SIZE: size,
            CONF_DEVICE_KEY: device_key,
            CONF_MAC: mac,
        }
        kwargs = dict(domain=DOMAIN, data=data, options=options or {})
        if entry_id is not None:
            kwargs["entry_id"] = entry_id
        return MockConfigEntry(**kwargs)

    return _make


@pytest.fixture
def make_scenes_hub_entry():
    """Factory for the auto-created, device-less scenes-hub config entry
    (entry.data == {"kind": KIND_SCENES_HUB}) -- distinct shape from a frame
    entry, see const.py / __init__.py's async_setup_entry branch on it."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.fraimic.const import DOMAIN, KIND_SCENES_HUB

    def _make():
        return MockConfigEntry(domain=DOMAIN, data={"kind": KIND_SCENES_HUB})

    return _make


@pytest.fixture
def make_coordinator(hass):
    """Build a FraimicCoordinator the way real entry setup does, including
    the `current_entry` ContextVar that HA's own DataUpdateCoordinator base
    class reads in this HA version when a coordinator subclass doesn't pass
    config_entry= explicitly to super().__init__() (this integration's
    coordinator.py doesn't) -- without it, self.config_entry silently ends
    up None outside of a real entry-setup call stack."""
    from homeassistant.config_entries import current_entry

    from custom_components.fraimic.coordinator import FraimicCoordinator

    def _make(entry):
        entry.add_to_hass(hass)
        token = current_entry.set(entry)
        try:
            return FraimicCoordinator(hass, entry)
        finally:
            current_entry.reset(token)

    return _make


@pytest.fixture
def sample_image_bytes():
    """Small deterministic source images for image_converter tests, at a
    few orientations. Built in-memory (no fixture files to keep in sync)."""
    from PIL import Image
    import io

    def _make(width: int, height: int, color=(200, 50, 50), fmt: str = "PNG") -> bytes:
        img = Image.new("RGB", (width, height), color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()

    return _make
