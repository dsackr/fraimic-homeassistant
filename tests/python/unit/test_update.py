"""Integration self-update helpers (KPF 33)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.update import (
    _NEEDS_RESTART_KEY,
    _needs_restart,
    _norm_version,
    _version_tuple,
    is_newer,
)


def test_norm_version_strips_v_prefix():
    assert _norm_version("v0.12.102") == "0.12.102"
    assert _norm_version("0.12.102") == "0.12.102"
    assert _norm_version(None) == ""


def test_version_tuple_numeric():
    assert _version_tuple("0.12.102") == (0, 12, 102)
    assert _version_tuple("1.0") == (1, 0)


def test_is_newer():
    assert is_newer("0.12.103", "0.12.102") is True
    assert is_newer("0.12.102", "0.12.102") is False
    assert is_newer("0.12.101", "0.12.102") is False
    assert is_newer("v0.13.0", "0.12.99") is True
    assert is_newer("1.0.0", "0.99.99") is True


def test_needs_restart_when_disk_ahead_of_running():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    assert _needs_restart(hass, disk="0.12.111", running="0.12.108") is True
    assert _needs_restart(hass, disk="0.12.111", running="0.12.111") is False


def test_needs_restart_sticky_flag():
    hass = MagicMock()
    hass.data = {DOMAIN: {_NEEDS_RESTART_KEY: True}}
    assert _needs_restart(hass, disk="0.12.111", running="0.12.111") is True
