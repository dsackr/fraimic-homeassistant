"""Integration self-update helpers (KPF 33)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.update import (
    GITHUB_FULL,
    _NEEDS_RESTART_KEY,
    _find_hacs_repo,
    _hacs_ref_for_target,
    _needs_restart,
    _norm_version,
    _sync_hacs_after_install,
    _try_hacs_install,
    _version_tuple,
    banner_visible,
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


def test_banner_visible_when_update_and_not_dismissed():
    assert banner_visible(
        update_available=True, latest="0.12.120", dismissed=""
    ) is True
    assert banner_visible(
        update_available=True, latest="0.12.120", dismissed="0.12.100"
    ) is True
    # Dismissed this exact version → hide
    assert banner_visible(
        update_available=True, latest="0.12.120", dismissed="0.12.120"
    ) is False
    assert banner_visible(
        update_available=True, latest="v0.12.120", dismissed="0.12.120"
    ) is False
    # No update → never show
    assert banner_visible(
        update_available=False, latest="0.12.120", dismissed=""
    ) is False
    # Newer release after dismiss re-shows
    assert banner_visible(
        update_available=True, latest="0.12.121", dismissed="0.12.120"
    ) is True


def test_needs_restart_when_disk_ahead_of_running():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    assert _needs_restart(hass, disk="0.12.111", running="0.12.108") is True
    assert _needs_restart(hass, disk="0.12.111", running="0.12.111") is False


def test_needs_restart_sticky_flag():
    hass = MagicMock()
    hass.data = {DOMAIN: {_NEEDS_RESTART_KEY: True}}
    assert _needs_restart(hass, disk="0.12.111", running="0.12.111") is True


def test_find_hacs_repo_by_full_name():
    hass = MagicMock()
    repo = SimpleNamespace(data=SimpleNamespace(full_name=GITHUB_FULL))
    repos = SimpleNamespace(get_by_full_name=lambda name: repo if name == GITHUB_FULL else None)
    hass.data = {"hacs": SimpleNamespace(repositories=repos)}
    assert _find_hacs_repo(hass) is repo


def test_find_hacs_repo_missing():
    hass = MagicMock()
    hass.data = {}
    assert _find_hacs_repo(hass) is None


def test_hacs_ref_prefers_matching_last_version_tag():
    repo = SimpleNamespace(data=SimpleNamespace(last_version="v0.12.120"))
    assert _hacs_ref_for_target(repo, "0.12.120", "v0.12.120") == "v0.12.120"
    # Preferred tag wins when it matches target
    assert _hacs_ref_for_target(repo, "0.12.120", "0.12.120") in ("0.12.120", "v0.12.120")


@pytest.mark.asyncio
async def test_sync_hacs_after_install_sets_installed_version():
    """Zipball path must update HACS so HA's update entity matches disk (KPF 33)."""
    hass = MagicMock()
    data = SimpleNamespace(
        full_name=GITHUB_FULL,
        installed=True,
        installed_version="v0.12.100",
        new=True,
        id="12345",
    )
    repo = SimpleNamespace(data=data, pending_restart=False)
    writer = AsyncMock()
    hacs = SimpleNamespace(
        repositories=SimpleNamespace(get_by_full_name=lambda _n: repo),
        data=SimpleNamespace(async_write=writer),
        async_dispatch=MagicMock(),
    )
    hass.data = {"hacs": hacs}

    result = await _sync_hacs_after_install(hass, tag="v0.12.120", version="0.12.120")

    assert result["synced"] is True
    assert data.installed is True
    assert data.installed_version == "v0.12.120"
    assert data.new is False
    assert repo.pending_restart is True
    writer.assert_awaited()


@pytest.mark.asyncio
async def test_sync_hacs_after_install_no_hacs():
    hass = MagicMock()
    hass.data = {}
    result = await _sync_hacs_after_install(hass, tag="v0.12.120", version="0.12.120")
    assert result["synced"] is False
    assert result["reason"] == "hacs_not_tracking"


@pytest.mark.asyncio
async def test_try_hacs_install_uses_async_download_repository(monkeypatch):
    """Modern HACS API must be used (old code only looked for .download)."""
    hass = MagicMock()
    data = SimpleNamespace(
        full_name=GITHUB_FULL,
        installed=True,
        installed_version="v0.12.100",
        last_version="v0.12.120",
        id="99",
    )
    download = AsyncMock()
    repo = SimpleNamespace(
        data=data,
        async_download_repository=download,
        pending_restart=False,
    )
    writer = AsyncMock()
    hacs = SimpleNamespace(
        repositories=SimpleNamespace(get_by_full_name=lambda _n: repo),
        data=SimpleNamespace(async_write=writer),
    )
    hass.data = {DOMAIN: {}, "hacs": hacs}

    async def _disk(_hass):
        return "0.12.120"

    async def _running(_hass):
        return "0.12.100"

    monkeypatch.setattr(
        "custom_components.fraimic.update.get_disk_version", _disk
    )
    monkeypatch.setattr(
        "custom_components.fraimic.update.get_running_version", _running
    )

    result = await _try_hacs_install(hass, "0.12.120", tag="v0.12.120")

    assert result is not None
    assert result["method"] == "hacs"
    assert result["needs_restart"] is True
    download.assert_awaited_once()
    # Called with ref= matching the release tag
    assert download.await_args.kwargs.get("ref") == "v0.12.120"
    writer.assert_awaited()


@pytest.mark.asyncio
async def test_try_hacs_install_skips_when_not_installed_via_hacs():
    hass = MagicMock()
    data = SimpleNamespace(full_name=GITHUB_FULL, installed=False, last_version="v0.12.120")
    repo = SimpleNamespace(data=data, async_download_repository=AsyncMock())
    hacs = SimpleNamespace(
        repositories=SimpleNamespace(get_by_full_name=lambda _n: repo),
        data=SimpleNamespace(async_write=AsyncMock()),
    )
    hass.data = {"hacs": hacs}
    result = await _try_hacs_install(hass, "0.12.120", tag="v0.12.120")
    assert result is None
    repo.async_download_repository.assert_not_awaited()


@pytest.mark.asyncio
async def test_install_update_hacs_sync_only_when_disk_current(monkeypatch):
    """When disk already has target but HACS is stale, only re-register HACS."""
    from custom_components.fraimic import update as update_mod

    hass = MagicMock()
    data = SimpleNamespace(
        full_name=GITHUB_FULL,
        installed=True,
        installed_version="v0.12.100",
        last_version="v0.12.120",
        new=False,
        id="1",
    )
    repo = SimpleNamespace(data=data, pending_restart=False)
    writer = AsyncMock()
    hacs = SimpleNamespace(
        repositories=SimpleNamespace(get_by_full_name=lambda _n: repo),
        data=SimpleNamespace(async_write=writer),
        async_dispatch=MagicMock(),
    )
    hass.data = {DOMAIN: {}, "hacs": hacs}

    async def fake_check(_hass):
        return {
            "installed": "0.12.120",
            "running": "0.12.120",
            "disk": "0.12.120",
            "latest": "0.12.120",
            "latest_tag": "v0.12.120",
            "update_available": False,
            "needs_restart": False,
            "hacs": {
                "present": True,
                "tracks_fraimic": True,
                "installed_version": "0.12.100",
                "desynced_with_disk": True,
            },
            "zipball_url": "https://example.invalid/zip",
        }

    monkeypatch.setattr(update_mod, "check_for_update", fake_check)
    monkeypatch.setattr(update_mod, "get_running_version", AsyncMock(return_value="0.12.120"))
    # Ensure we never hit the network if the recovery path fails
    monkeypatch.setattr(
        update_mod, "_install_from_zipball", AsyncMock(side_effect=AssertionError("no zip"))
    )
    monkeypatch.setattr(
        update_mod, "_try_hacs_install", AsyncMock(side_effect=AssertionError("no hacs dl"))
    )

    result = await update_mod.install_update(hass)
    assert result["method"] == "hacs_sync_only"
    assert result["success"] is True
    assert data.installed_version == "v0.12.120"
    writer.assert_awaited()


@pytest.mark.asyncio
async def test_check_for_update_auto_heals_hacs_desync(monkeypatch):
    """Opening Settings / checking updates fixes stale HACS without user action."""
    from custom_components.fraimic import update as update_mod

    hass = MagicMock()
    data = SimpleNamespace(
        full_name=GITHUB_FULL,
        installed=True,
        installed_version="v0.12.100",
        last_version="v0.12.120",
        new=False,
        id="1",
    )
    repo = SimpleNamespace(data=data, pending_restart=False)
    writer = AsyncMock()
    hacs = SimpleNamespace(
        repositories=SimpleNamespace(get_by_full_name=lambda _n: repo),
        data=SimpleNamespace(async_write=writer),
        async_dispatch=MagicMock(),
    )
    hass.data = {DOMAIN: {}, "hacs": hacs}

    monkeypatch.setattr(
        update_mod, "get_disk_version", AsyncMock(return_value="0.12.120")
    )
    monkeypatch.setattr(
        update_mod, "get_running_version", AsyncMock(return_value="0.12.120")
    )
    monkeypatch.setattr(
        update_mod,
        "fetch_latest_release",
        AsyncMock(
            return_value={
                "tag": "v0.12.120",
                "version": "0.12.120",
                "name": "v0.12.120",
                "body": "",
                "html_url": "https://example.invalid",
                "zipball_url": "https://example.invalid/zip",
            }
        ),
    )

    result = await update_mod.check_for_update(hass)

    assert result["hacs_healed"] is True
    assert data.installed_version == "v0.12.120"
    assert result["hacs"]["desynced_with_disk"] is False
    writer.assert_awaited()
