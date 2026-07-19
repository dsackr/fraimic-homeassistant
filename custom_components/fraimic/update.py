"""Self-update helpers: check GitHub for a newer Fraimic release and install it.

Keeps users off the HACS → Settings → Restart obstacle course when all they
want is "is there a new Fraimic, and can I install it from here?".

Install strategy (in order):

1. If HACS has ``dsackr/fraimic-homeassistant`` installed, call HACS's
   ``async_download_repository`` / ``async_install`` so files **and** HACS
   bookkeeping (``installed_version``, HA update entity) stay in sync.
2. Otherwise download the GitHub tag zipball and replace
   ``custom_components/fraimic`` in place (backup goes under
   ``.storage/fraimic_update_backup/``, never under custom_components/).
   When HACS still tracks the repo, we then **sync** its
   ``installed_version`` + store so Settings → Devices & services / the
   HACS update entity register the new release after restart — without
   this step zipball installs leave HACS stuck on the old version forever.

A full Home Assistant restart is still required after install for the new
code (and panel cache-bust URL) to load cleanly.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import time
import zipfile
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .const import DOMAIN

# Set after a successful disk install until HA restarts and running==disk.
_NEEDS_RESTART_KEY = "_update_needs_restart"
# In-memory cache of the last GitHub release probe (avoids hitting the
# network on every dashboard open when the update banner checks status).
_RELEASE_CACHE_KEY = "_update_release_cache"
_RELEASE_CACHE_TTL_S = 6 * 3600
# Server-side dismiss for the "new version available" banner — keyed by
# the dismissed *latest* version so a newer release re-shows the banner.
_BANNER_STORE_KEY = f"{DOMAIN}_update_banner"
_BANNER_STORE_VERSION = 1
_BANNER_STORE_CACHE = "_update_banner_store"

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


async def get_running_version(hass: HomeAssistant) -> str:
    """Version HA has loaded into memory (stale until restart after update)."""
    try:
        integration = await async_get_integration(hass, DOMAIN)
        return _norm_version(str(integration.version or ""))
    except Exception:  # noqa: BLE001
        return ""


async def get_disk_version(hass: HomeAssistant) -> str:
    """Version in ``custom_components/fraimic/manifest.json`` on disk."""
    path = hass.config.path("custom_components", _COMPONENT, "manifest.json")

    def _read() -> str:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return _norm_version(str(data.get("version") or ""))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return ""

    return await hass.async_add_executor_job(_read)


async def get_installed_version(hass: HomeAssistant) -> str:
    """On-disk package version (preferred after a Settings-page install)."""
    disk = await get_disk_version(hass)
    if disk:
        return disk
    return await get_running_version(hass)


def _mark_needs_restart(hass: HomeAssistant) -> None:
    hass.data.setdefault(DOMAIN, {})[_NEEDS_RESTART_KEY] = True


def _needs_restart(hass: HomeAssistant, *, disk: str, running: str) -> bool:
    if hass.data.get(DOMAIN, {}).get(_NEEDS_RESTART_KEY):
        return True
    if disk and running and disk != running:
        return True
    return False


def _banner_store(hass: HomeAssistant) -> Store:
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = domain_data.get(_BANNER_STORE_CACHE)
    if store is None:
        store = Store(hass, _BANNER_STORE_VERSION, _BANNER_STORE_KEY)
        domain_data[_BANNER_STORE_CACHE] = store
    return store


async def get_banner_dismissed_version(hass: HomeAssistant) -> str:
    """Return the latest version the admin last dismissed (or empty)."""
    try:
        data = await _banner_store(hass).async_load() or {}
    except Exception:  # noqa: BLE001
        return ""
    return _norm_version(str(data.get("dismissed_version") or ""))


async def dismiss_update_banner(hass: HomeAssistant, version: str) -> dict[str, Any]:
    """Dismiss the dashboard banner for *version* (normalized).

    A later release with a higher version re-shows the banner automatically.
    """
    ver = _norm_version(version)
    if not ver:
        raise UpdateError("version is required to dismiss the update banner")
    await _banner_store(hass).async_save({"dismissed_version": ver})
    return {"success": True, "dismissed_version": ver}


def banner_visible(*, update_available: bool, latest: str, dismissed: str) -> bool:
    """True when a new version is available and not dismissed for that version."""
    if not update_available or not latest:
        return False
    return _norm_version(latest) != _norm_version(dismissed)


async def fetch_latest_release(
    hass: HomeAssistant, *, force: bool = False
) -> dict[str, Any]:
    """Return {tag, version, name, body, html_url, tarball_url, zipball_url}.

    Results are cached in ``hass.data`` for a few hours so the dashboard
    banner can poll status without hammering GitHub. Pass *force* to bypass.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    cached = domain_data.get(_RELEASE_CACHE_KEY)
    now = time.time()
    if (
        not force
        and isinstance(cached, dict)
        and cached.get("data")
        and now - float(cached.get("ts") or 0) < _RELEASE_CACHE_TTL_S
    ):
        return dict(cached["data"])

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
    result = {
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
    domain_data[_RELEASE_CACHE_KEY] = {"ts": now, "data": result}
    return dict(result)


async def check_for_update(
    hass: HomeAssistant, *, force: bool = False
) -> dict[str, Any]:
    """Compare on-disk package version to latest GitHub release.

    Also reports the version HA currently has loaded (*running*). After an
    install without restart, *installed* (disk) can be newer than *running*
    — that is expected; *needs_restart* is True until they match.

    If HACS tracks Fraimic but its ``installed_version`` lags the on-disk
    package (legacy zipball-only installs), heal that bookkeeping here so
    the user never has to "re-sync" manually.

    Includes ``banner_visible`` for the dashboard "new version" banner
    (false when the admin dismissed this *latest* version).
    """
    disk = await get_disk_version(hass)
    running = await get_running_version(hass)
    installed = disk or running
    latest = await fetch_latest_release(hass, force=force)
    available = is_newer(latest["version"], installed)
    dismissed = await get_banner_dismissed_version(hass)
    show_banner = banner_visible(
        update_available=available,
        latest=latest["version"],
        dismissed=dismissed,
    )
    hacs = await _hacs_status(hass)
    hacs_healed = False
    if (
        disk
        and hacs
        and hacs.get("tracks_fraimic")
        and hacs.get("desynced_with_disk")
    ):
        # Prefer GitHub's tag spelling when it matches disk; else v{disk}.
        tag = latest["tag"] if _norm_version(latest["version"]) == _norm_version(disk) else f"v{disk}"
        sync = await _sync_hacs_after_install(hass, tag=tag, version=disk)
        if sync.get("synced"):
            hacs_healed = True
            hacs = await _hacs_status(hass)
    needs_restart = _needs_restart(hass, disk=disk, running=running)
    # Clear sticky flag once a restart has aligned versions.
    if disk and running and disk == running:
        hass.data.setdefault(DOMAIN, {}).pop(_NEEDS_RESTART_KEY, None)
        needs_restart = False
    return {
        "installed": installed,
        "running": running,
        "disk": disk,
        "latest": latest["version"],
        "latest_tag": latest["tag"],
        "latest_name": latest["name"],
        "release_notes": latest["body"],
        "release_url": latest["html_url"],
        "update_available": available,
        "banner_visible": show_banner,
        "banner_dismissed_version": dismissed,
        "needs_restart": needs_restart,
        "hacs": hacs,
        "hacs_healed": hacs_healed,
        "zipball_url": latest["zipball_url"],
    }


def _find_hacs_repo(hass: HomeAssistant) -> Any | None:
    """Return the HACS repository object for our GitHub full name, or None."""
    hacs = hass.data.get("hacs")
    if hacs is None:
        return None
    repos = getattr(hacs, "repositories", None)
    if repos is None:
        return None
    getter = getattr(repos, "get_by_full_name", None)
    if callable(getter):
        repo = getter(GITHUB_FULL)
        if repo is not None:
            return repo
    # Fallback: scan list_all / list_downloaded
    for attr in ("list_downloaded", "list_all"):
        listing = getattr(repos, attr, None)
        items = listing() if callable(listing) else listing
        for r in items or []:
            data = getattr(r, "data", None)
            full = getattr(data, "full_name", None) or getattr(r, "full_name", "")
            if str(full).lower() == GITHUB_FULL.lower():
                return r
    return None


def _hacs_ref_for_target(repo: Any, target: str, preferred_tag: str) -> str:
    """Pick a ref string HACS will accept (usually the GitHub tag name)."""
    data = getattr(repo, "data", None)
    candidates = [
        preferred_tag,
        getattr(data, "last_version", None) if data is not None else None,
        f"v{target}" if not str(target).startswith("v") else target,
        target,
    ]
    for c in candidates:
        if not c:
            continue
        if _norm_version(str(c)) == _norm_version(target) or not target:
            return str(c)
    return preferred_tag or f"v{target}"


async def _persist_hacs_data(hass: HomeAssistant) -> bool:
    """Force HACS to write repository state (installed_version) to .storage."""
    hacs = hass.data.get("hacs")
    if hacs is None:
        return False
    data = getattr(hacs, "data", None)
    writer = getattr(data, "async_write", None) if data is not None else None
    if not callable(writer):
        return False
    try:
        # force=True so a temporarily-disabled HACS still persists.
        await writer(force=True)
        return True
    except TypeError:
        await writer()
        return True


async def _sync_hacs_after_install(
    hass: HomeAssistant, *, tag: str, version: str
) -> dict[str, Any]:
    """Align HACS bookkeeping with a successful on-disk install.

    Without this, a zipball install updates files but leaves HACS (and the
    HA ``update`` entity it owns) stuck on the previous ``installed_version``,
    so after restart HA still reports an available update / old version.
    """
    repo = _find_hacs_repo(hass)
    if repo is None:
        return {"synced": False, "reason": "hacs_not_tracking"}

    data = getattr(repo, "data", None)
    if data is None:
        return {"synced": False, "reason": "no_repo_data"}

    ref = _hacs_ref_for_target(repo, version, tag)
    try:
        data.installed = True
        data.installed_version = ref
        # Clear "new" badge so it shows as a normal installed integration.
        if hasattr(data, "new"):
            data.new = False
        # HACS integration repos flag a restart after install.
        if hasattr(repo, "pending_restart"):
            repo.pending_restart = True

        wrote = await _persist_hacs_data(hass)

        # Nudge HACS UI / update entities (best-effort; string matches HACS 2.x).
        dispatch = getattr(hass.data.get("hacs"), "async_dispatch", None)
        if callable(dispatch):
            try:
                dispatch(
                    "hacs/repository",
                    {
                        "id": 1337,
                        "action": "install",
                        "repository": GITHUB_FULL,
                        "repository_id": str(getattr(data, "id", "") or ""),
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        _LOGGER.info(
            "Synced HACS installed_version=%s for %s (persisted=%s)",
            ref,
            GITHUB_FULL,
            wrote,
        )
        return {
            "synced": True,
            "installed_version": ref,
            "persisted": wrote,
        }
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed to sync HACS after install: %s", err)
        return {"synced": False, "reason": str(err)}


async def _hacs_status(hass: HomeAssistant) -> dict[str, Any] | None:
    """If HACS is present and tracks our repo, surface its view of versions."""
    hacs = hass.data.get("hacs")
    if hacs is None:
        return None
    try:
        repo = _find_hacs_repo(hass)
        if repo is None:
            return {"present": True, "tracks_fraimic": False}
        data = getattr(repo, "data", repo)
        raw_installed = str(
            getattr(data, "installed_version", "")
            or getattr(data, "version_installed", "")
            or ""
        )
        installed = _norm_version(raw_installed)
        available = _norm_version(
            str(
                getattr(data, "last_version", "")
                or getattr(data, "available_version", "")
                or ""
            )
        )
        repo_id = getattr(data, "id", None)
        disk = await get_disk_version(hass)
        desynced = bool(
            disk
            and installed
            and _norm_version(disk) != installed
        )
        return {
            "present": True,
            "tracks_fraimic": True,
            "installed_version": installed,
            "installed_version_raw": raw_installed,
            "available_version": available,
            "repository_id": str(repo_id) if repo_id is not None else "",
            "desynced_with_disk": desynced,
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

    tag = status.get("latest_tag") or f"v{target}"
    if version and _norm_version(version) != status["latest"]:
        tag = version if str(version).startswith("v") else f"v{version}"

    disk_now = status.get("disk") or await get_disk_version(hass)
    # Recovery: files already match target but HACS still reports an older
    # installed_version (the pre-fix zipball path). Just re-register HACS.
    hacs_info = status.get("hacs") or {}
    if (
        disk_now
        and _norm_version(disk_now) == _norm_version(target)
        and hacs_info.get("tracks_fraimic")
        and (
            hacs_info.get("desynced_with_disk")
            or (
                hacs_info.get("installed_version")
                and _norm_version(hacs_info["installed_version"]) != _norm_version(target)
            )
        )
    ):
        hacs_sync = await _sync_hacs_after_install(hass, tag=tag, version=target)
        running = await get_running_version(hass)
        needs = _needs_restart(hass, disk=disk_now, running=running)
        if needs:
            _mark_needs_restart(hass)
        return {
            "success": True,
            "method": "hacs_sync_only",
            "installed": disk_now,
            "running": running,
            "disk": disk_now,
            "needs_restart": needs,
            "hacs_sync": hacs_sync,
            "message": (
                f"Fraimic {disk_now} was already on disk; "
                + (
                    "HACS is now registered to that version."
                    if hacs_sync.get("synced")
                    else f"HACS sync failed ({hacs_sync.get('reason', 'unknown')})."
                )
                + (
                    " Restart Home Assistant if the running version still differs."
                    if needs
                    else ""
                )
            ),
        }

    # Prefer HACS when it tracks us and exposes a modern download path.
    hacs_result = await _try_hacs_install(hass, target, tag=tag)
    if hacs_result is not None:
        _mark_needs_restart(hass)
        return hacs_result

    zip_url = (
        status.get("zipball_url")
        if (not version or _norm_version(version) == status["latest"])
        else f"https://github.com/{GITHUB_FULL}/archive/refs/tags/{tag}.zip"
    )
    await _install_from_zipball(hass, zip_url, expected_version=target)
    hacs_sync = await _sync_hacs_after_install(hass, tag=tag, version=target)
    _mark_needs_restart(hass)
    disk = await get_disk_version(hass) or target
    running = await get_running_version(hass)
    if disk and _norm_version(disk) != _norm_version(target):
        _LOGGER.warning(
            "Post-install disk version %s does not match target %s",
            disk,
            target,
        )
    hacs_note = ""
    if hacs_sync.get("synced"):
        hacs_note = " HACS registered the new version."
    elif hacs_sync.get("reason") and hacs_sync["reason"] != "hacs_not_tracking":
        hacs_note = f" (HACS sync skipped: {hacs_sync['reason']})"
    return {
        "success": True,
        "method": "github",
        "installed": disk,
        "running": running,
        "disk": disk,
        "needs_restart": True,
        "hacs_sync": hacs_sync,
        "message": (
            f"Fraimic {disk} is on disk"
            + (f" (Home Assistant is still running {running})" if running and running != disk else "")
            + f".{hacs_note} Restart Home Assistant to load it."
        ),
    }


async def _try_hacs_install(
    hass: HomeAssistant, target: str, *, tag: str
) -> dict[str, Any] | None:
    """Attempt HACS download; return result dict or None to fall back.

    Modern HACS (2.x) exposes ``async_download_repository(ref=…)`` and
    ``async_install(version=…)``. Older guesses (``download`` /
    ``async_download``) never matched, so every install fell through to
    zipball and left HACS's installed_version stale.
    """
    hacs = hass.data.get("hacs")
    if hacs is None:
        return None
    try:
        repo = _find_hacs_repo(hass)
        if repo is None:
            return None

        data = getattr(repo, "data", None)
        # Only use HACS download when the repo is already an installed HACS
        # package (otherwise zipball + optional registration is clearer).
        if data is not None and not getattr(data, "installed", False):
            return None

        ref = _hacs_ref_for_target(repo, target, tag)

        download_repo = getattr(repo, "async_download_repository", None)
        install_fn = getattr(repo, "async_install", None)
        legacy = getattr(repo, "download", None) or getattr(repo, "async_download", None)

        if callable(download_repo):
            await download_repo(ref=ref)
        elif callable(install_fn):
            await install_fn(version=ref)
        elif callable(legacy):
            if asyncio.iscoroutinefunction(legacy):
                await legacy(ref)
            else:
                result = legacy(ref)
                if asyncio.iscoroutine(result):
                    await result
        else:
            _LOGGER.debug(
                "HACS tracks %s but exposes no download API; using zipball",
                GITHUB_FULL,
            )
            return None

        # HACS websocket path always persists after download; mirror that.
        await _persist_hacs_data(hass)
        # Belt-and-suspenders: ensure installed_version matches what we asked for.
        if data is not None:
            if not getattr(data, "installed_version", None) or _norm_version(
                str(data.installed_version)
            ) != _norm_version(target):
                data.installed = True
                data.installed_version = ref
                await _persist_hacs_data(hass)
        if hasattr(repo, "pending_restart"):
            repo.pending_restart = True

        _mark_needs_restart(hass)
        disk = await get_disk_version(hass) or target
        running = await get_running_version(hass)
        return {
            "success": True,
            "method": "hacs",
            "installed": disk,
            "running": running,
            "disk": disk,
            "needs_restart": True,
            "hacs_sync": {"synced": True, "installed_version": ref, "persisted": True},
            "message": (
                f"Fraimic {disk} installed via HACS"
                + (
                    f" (Home Assistant is still running {running})"
                    if running and running != disk
                    else ""
                )
                + ". Restart Home Assistant to load it."
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
