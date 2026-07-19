"""Integration self-update helpers (KPF 33)."""

from __future__ import annotations

from custom_components.fraimic.update import is_newer, _norm_version, _version_tuple


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
