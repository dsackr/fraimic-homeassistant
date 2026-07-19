"""Self-update helpers: check GitHub for a newer Fraimic release and install it.

Keeps users off the HACS → Settings → Restart obstacle course when all they
want is "is there a new Fraimic, and can I install it from here?".

Install strategy (in order):

1. If HACS has ``dsackr/fraimic-homeassistant`` downloaded, use HACS's
   repository download so HACS stays in sync with on-disk files.
2. Otherwise download the GitHub tag zipball and replace
   ``custom_components/fraimic`` in place (backup goes under
   ``.storage/fraimic_update_backup/``, never under custom_components/).

A full Home Assistant restart is still required after install for the new
code (and panel cache-bust URL) to load cleanly.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import zipfile
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GITHUB_OWNER = "dsackr"
GITHUB_REPO = "fraimic-homeassistant"
GITHUB_FULL = f"{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_FULL}/releases/latest"
)
GITHUB_API_RELEASES = (
    f"https://api.github.com/repos/{GITHUB_FULL}/releases?per_page=5"
)

# Component directory name inside the repo zip and under config/.
_COMPONENT = "fraimic"


class UpdateError(Exception):
    """User-facing update failure."""


def _norm_version(v: str | None) -> str:
    if not v:
        return ""
    return str(v).lstrip("vV").strip()


def _version_tuple(v: str) -> tuple[int, ...]:
    """Best-effort numeric compare; non-numeric tails sort as 0."""
    parts: list[int] = []
    for p in _norm_version(v).split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    """True when *candidate* is strictly newer than *current*."""
    if not candidate or not current:
        return bool(candidate and not current)
    return _version_tuple(candidate) > _version_tuple(current)


async def get_installed_version(hass: HomeAssistant) -> str:
    integration = await async_get_integration(hass, DOMAIN)
    return _norm_version(str(integration.version or ""))


async def fetch_latest_release(hass: HomeAssistant) -> dict[str, Any]:
    """Return {tag, version, name, body, html_url, tarball_url, zipball_url}."""
    session = async_get_clientsession(hass)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"fraimic-homeassistant/{DOMAIN}",
    }
    try:
        async with session.get(
            GITHUB_API_LATEST,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 404:
                # No formal release yet — fall back to most recent tag-ish release list.
                async with session.get(
                    GITHUB_API_RELEASES,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as r2:
                    r2.raise_for_status()
                    items = await r2.json()
                if not items:
                    raise UpdateError("No GitHub releases found for Fraimic")
                data = items[0]
            else:
                resp.raise_for_status()
                data = await resp.json()
    except aiohttp.ClientError as err:
        raise UpdateError(f"Could not reach GitHub: {err}") from err

    tag = data.get("tag_name") or ""
    return {
        "tag": tag,
        "version": _norm_version(tag),
        "name": data.get("name") or tag,
        "body": (data.get("body") or "")[:4000],
        "html_url": data.get("html_url") or "",
        "tarball_url": data.get("tarball_url") or "",
        "zipball_url": data.get("zipball_url")
        or f"https://github.com/{GITHUB_FULL}/archive/refs/tags/{tag}.zip",
        "published_at": data.get("published_at") or "",
    }


async def check_for_update(hass: HomeAssistant) -> dict[str, Any]:
    """Compare installed version to latest GitHub release."""
    installed = await get_installed_version(hass)
    latest = await fetch_latest_release(hass)
    available = is_newer(latest["version"], installed)
    hacs = await _hacs_status(hass)
    return {
        "installed": installed,
        "latest": latest["version"],
        "latest_tag": latest["tag"],
        "latest_name": latest["name"],
        "release_notes": latest["body"],
        "release_url": latest["html_url"],
        "update_available": available,
        "hacs": hacs,
        "zipball_url": latest["zipball_url"],
    }


async def _hacs_status(hass: HomeAssistant) -> dict[str, Any] | None:
    """If HACS is present and tracks our repo, surface its view of versions."""
    hacs = hass.data.get("hacs")
    if hacs is None:
        return None
    try:
        repos = getattr(hacs, "repositories", None)
        if repos is None:
            return None
        # HACS 2.x: repositories.get_by_full_name / list_downloaded
        repo = None
        getter = getattr(repos, "get_by_full_name", None)
        if callable(getter):
            repo = getter(GITHUB_FULL)
        if repo is None:
            for r in getattr(repos, "list_all", []) or []:
                data = getattr(r, "data", None)
                full = getattr(data, "full_name", None) or getattr(r, "full_name", "")
                if str(full).lower() == GITHUB_FULL.lower():
                    repo = r
                    break
        if repo is None:
            return {"present": True, "tracks_fraimic": False}
        data = getattr(repo, "data", repo)
        installed = _norm_version(
            str(getattr(data, "installed_version", "") or getattr(data, "version_installed", "") or "")
        )
        available = _norm_version(
            str(getattr(data, "last_version", "") or getattr(data, "available_version", "") or "")
        )
        repo_id = getattr(data, "id", None)
        return {
            "present": True,
            "tracks_fraimic": True,
            "installed_version": installed,
            "available_version": available,
            "repository_id": str(repo_id) if repo_id is not None else "",
        }
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("HACS status probe failed: %s", err)
        return {"present": True, "tracks_fraimic": False, "error": str(err)}


async def install_update(hass: HomeAssistant, *, version: str | None = None) -> dict[str, Any]:
    """Install *version* (or latest) onto disk. Does not restart HA."""
    status = await check_for_update(hass)
    target = _norm_version(version) or status["latest"]
    if not target:
        raise UpdateError("No target version to install")

    # Prefer HACS when it tracks us and exposes a download path.
    hacs_result = await _try_hacs_install(hass, target)
    if hacs_result is not None:
        return hacs_result

    tag = status.get("latest_tag") or f"v{target}"
    if version and _norm_version(version) != status["latest"]:
        tag = version if str(version).startswith("v") else f"v{version}"

    zip_url = (
        status.get("zipball_url")
        if (not version or _norm_version(version) == status["latest"])
        else f"https://github.com/{GITHUB_FULL}/archive/refs/tags/{tag}.zip"
    )
    await _install_from_zipball(hass, zip_url, expected_version=target)
    return {
        "success": True,
        "method": "github",
        "installed": target,
        "needs_restart": True,
        "message": (
            f"Fraimic {target} installed. Restart Home Assistant to load it."
        ),
    }


async def _try_hacs_install(hass: HomeAssistant, target: str) -> dict[str, Any] | None:
    """Attempt HACS download; return result dict or None to fall back."""
    hacs = hass.data.get("hacs")
    if hacs is None:
        return None
    try:
        repos = getattr(hacs, "repositories", None)
        if repos is None:
            return None
        repo = None
        getter = getattr(repos, "get_by_full_name", None)
        if callable(getter):
            repo = getter(GITHUB_FULL)
        if repo is None:
            return None

        # HACS repository object: async_download_repository / download
        download = getattr(repo, "download", None) or getattr(repo, "async_download", None)
        if download is None:
            # HACS 2 coordinator-style
            return None

        tag = f"v{target}" if not str(target).startswith("v") else target
        if asyncio.iscoroutinefunction(download):
            await download(tag)
        else:
            result = download(tag)
            if asyncio.iscoroutine(result):
                await result
        return {
            "success": True,
            "method": "hacs",
            "installed": target,
            "needs_restart": True,
            "message": (
                f"Fraimic {target} installed via HACS. Restart Home Assistant to load it."
            ),
        }
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("HACS install path failed, falling back to GitHub: %s", err)
        return None


async def _install_from_zipball(
    hass: HomeAssistant, zip_url: str, *, expected_version: str
) -> None:
    session = async_get_clientsession(hass)
    headers = {"User-Agent": f"fraimic-homeassistant/{DOMAIN}"}
    try:
        async with session.get(
            zip_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=120),
            allow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            payload = await resp.read()
    except aiohttp.ClientError as err:
        raise UpdateError(f"Download failed: {err}") from err

    dest = hass.config.path("custom_components", _COMPONENT)
    if not os.path.isdir(os.path.dirname(dest)):
        raise UpdateError("custom_components directory missing")

    def _extract() -> None:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            # GitHub zipball roots as <repo>-<tag>/custom_components/fraimic/...
            prefix = None
            for name in zf.namelist():
                marker = f"custom_components/{_COMPONENT}/"
                idx = name.find(marker)
                if idx >= 0:
                    prefix = name[: idx + len(marker)]
                    break
            if not prefix:
                raise UpdateError(
                    "Release archive does not contain custom_components/fraimic/"
                )

            backup_root = hass.config.path(".storage", "fraimic_update_backup")
            os.makedirs(backup_root, exist_ok=True)
            if os.path.isdir(dest):
                bak = os.path.join(
                    backup_root, f"{_COMPONENT}.bak.{expected_version or 'prev'}"
                )
                if os.path.exists(bak):
                    shutil.rmtree(bak)
                shutil.move(dest, bak)

            os.makedirs(dest, exist_ok=True)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not info.filename.startswith(prefix):
                    continue
                rel = info.filename[len(prefix) :]
                if not rel or rel.endswith("/"):
                    continue
                # Path-traversal guard
                out_path = os.path.normpath(os.path.join(dest, rel))
                if not out_path.startswith(os.path.normpath(dest) + os.sep) and out_path != os.path.normpath(dest):
                    continue
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with zf.open(info) as src, open(out_path, "wb") as out:
                    shutil.copyfileobj(src, out)

    try:
        await hass.async_add_executor_job(_extract)
    except UpdateError:
        raise
    except Exception as err:  # noqa: BLE001
        raise UpdateError(f"Extract failed: {err}") from err


async def restart_home_assistant(hass: HomeAssistant) -> None:
    """Schedule a Home Assistant restart (same as Settings → Restart)."""
    await hass.services.async_call("homeassistant", "restart", blocking=False)
