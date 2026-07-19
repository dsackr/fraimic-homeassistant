"""The Fraimic integration."""

from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import device_registry as dr

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    DOMAIN,
    HUB_PLATFORMS,
    KIND_SCENES_HUB,
    PLATFORMS,
)
from .coordinator import FraimicCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# panel_custom is a built-in HA component; import lazily to avoid load-order issues.
_PANEL_URL  = "/fraimic/fraimic-panel.js"
_PANEL_PATH = "fraimic"          # URL path: /fraimic
_PANEL_SIDEBAR_TITLE = "Frames"
_PANEL_SIDEBAR_ICON  = "mdi:image-frame"

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service schema definitions
# ---------------------------------------------------------------------------

_DEVICE_ID_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
    }
)

_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("media_content_id"): cv.string,
    }
)

_GENERATE_AI_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("prompt"): cv.string,
        vol.Optional("ai_task_entity_id"): cv.string,
    }
)

# AI-generated art always lands in its own album, kept separate from
# whatever the user's own uploads are organized into.
AI_GENERATED_ALBUM = "GenAI"

# ai_task.AITaskEntityFeature.GENERATE_IMAGE -- matches the bit the
# ai_task.generate_image service itself filters entities on.
_AI_TASK_GENERATE_IMAGE_FEATURE = 4

_SEND_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
    }
)

_SEND_SKILL_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("skill_id"): cv.string,
    }
)


# ---------------------------------------------------------------------------
# Domain-level setup (runs once when the domain is first loaded)
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register static paths, HTTP view, sidebar panel, and Lovelace card JS."""
    base_dir = hass.config.path("custom_components/fraimic")

    # Serve the Lovelace card JS and the sidebar panel JS at stable URLs.
    # Cache headers are ON: the ?v=<version> suffix below changes the URL
    # every release, so browsers can cache the ~200 KB panel bundle
    # aggressively without ever serving a stale one across upgrades.
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/fraimic/fraimic-card.js",
                f"{base_dir}/fraimic-card.js",
                True,
            ),
            StaticPathConfig(
                "/fraimic/fraimic-panel.js",
                f"{base_dir}/fraimic-panel.js",
                True,
            ),
        ]
    )

    # Cache-busting suffix for the card/panel JS URLs below -- tying the URL
    # to the integration version forces a real fetch of the new file every
    # time the version changes, instead of relying on users to hard-refresh.
    from homeassistant.loader import async_get_integration  # noqa: PLC0415

    integration = await async_get_integration(hass, DOMAIN)
    _cache_bust = integration.version or "dev"

    # Register the image-upload HTTP endpoint and the first-run wizard's
    # server-side completion flag.
    from .http_api import (  # noqa: PLC0415
        FraimicFrameStatusView,
        FraimicOnboardingView,
        FraimicSamsungContentView,
        FraimicSendImageView,
    )
    hass.http.register_view(FraimicSendImageView())
    hass.http.register_view(FraimicOnboardingView())
    hass.http.register_view(FraimicFrameStatusView())
    hass.http.register_view(FraimicSamsungContentView())

    from .update_http import async_register_update_views  # noqa: PLC0415

    async_register_update_views(hass)

    # Set up the shared image library (storage-backend agnostic) and its
    # HTTP endpoints. This is domain-level state, not per-frame, since the
    # library is shared across every configured frame.
    from .library import LibraryManager  # noqa: PLC0415

    library_manager = LibraryManager(hass)
    await library_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_library"] = library_manager

    # Voice/LLM: "generate an image of X and send it to [frame]" as a single
    # Assist tool, available the moment an LLM-backed conversation agent is
    # configured -- no user-authored script needed.
    from .intent import async_setup_intents  # noqa: PLC0415

    hass.async_create_task(async_setup_intents(hass))

    from .library_http import (  # noqa: PLC0415
        FraimicFramesView,
        FraimicFrameThumbnailView,
        FraimicLibraryAlbumImagesView,
        FraimicLibraryAlbumsView,
        FraimicLibraryCropView,
        FraimicLibraryDiscoverView,
        FraimicLibraryGoogleOAuthCallbackView,
        FraimicLibraryGoogleOAuthStartView,
        FraimicLibraryGoogleRedirectUriView,
        FraimicLibraryImageAlbumsView,
        FraimicLibraryImageVoiceNameView,
        FraimicLibraryImageTagsView,
        FraimicLibraryImageView,
        FraimicLibraryListView,
        FraimicLibrarySendView,
        FraimicLibrarySettingsView,
        FraimicLibraryUploadView,
        FraimicFrameReloadView,
    )

    hass.http.register_view(FraimicLibraryListView())
    hass.http.register_view(FraimicLibraryUploadView())
    hass.http.register_view(FraimicLibraryImageView())
    hass.http.register_view(FraimicLibraryImageAlbumsView())
    hass.http.register_view(FraimicLibraryImageVoiceNameView())
    hass.http.register_view(FraimicLibraryImageTagsView())
    hass.http.register_view(FraimicLibrarySendView())
    hass.http.register_view(FraimicLibraryCropView())
    hass.http.register_view(FraimicLibraryAlbumsView())
    hass.http.register_view(FraimicLibraryAlbumImagesView())
    hass.http.register_view(FraimicFramesView())
    hass.http.register_view(FraimicFrameThumbnailView())
    hass.http.register_view(FraimicLibrarySettingsView())
    hass.http.register_view(FraimicLibraryDiscoverView())
    hass.http.register_view(FraimicLibraryGoogleRedirectUriView())
    hass.http.register_view(FraimicLibraryGoogleOAuthStartView())
    hass.http.register_view(FraimicLibraryGoogleOAuthCallbackView())
    hass.http.register_view(FraimicFrameReloadView())

    # Scenes: named (frame, image) assignment lists sendable all at once.
    # Pure local state -- config entry_ids are meaningless off this HA
    # instance, so (unlike the library) there's no pluggable backend here.
    from .scenes import SceneManager  # noqa: PLC0415

    scene_manager = SceneManager(hass)
    await scene_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_scenes"] = scene_manager

    from .scenes_http import (  # noqa: PLC0415
        FraimicSceneSendView,
        FraimicSceneView,
        FraimicScenesView,
    )

    hass.http.register_view(FraimicScenesView())
    hass.http.register_view(FraimicSceneView())
    hass.http.register_view(FraimicSceneSendView())

    # Scheduled events: send a scene or a single image at a future time
    # (one-shot or daily/weekly/monthly). Built on the scene manager's
    # single send executor, so it's set up after it. Pure local state like
    # scenes -- entry_ids are meaningless off this HA instance.
    from .schedules import ScheduleManager  # noqa: PLC0415

    schedule_manager = ScheduleManager(hass)
    hass.data.setdefault(DOMAIN, {})["_schedules"] = schedule_manager
    await schedule_manager.async_load()

    from .schedules_http import (  # noqa: PLC0415
        FraimicSchedulesView,
        FraimicScheduleView,
    )

    hass.http.register_view(FraimicSchedulesView())
    hass.http.register_view(FraimicScheduleView())

    # Walls: virtual layouts of a subset of the user's frames, positioned the
    # way they're physically hung. Pure panel-local state -- like scenes,
    # config entry_ids are meaningless off this HA instance, and walls are
    # never referenced by automations, voice control, or an entity platform.
    from .walls import WallManager  # noqa: PLC0415

    wall_manager = WallManager(hass)
    await wall_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_walls"] = wall_manager

    # The default "All Frames" wall: guaranteed to exist and to track the
    # configured frames (config entries are already loaded at this point).
    await wall_manager.async_ensure_default_wall()

    from .walls_http import FraimicWallsView, FraimicWallView  # noqa: PLC0415

    hass.http.register_view(FraimicWallsView())
    hass.http.register_view(FraimicWallView())

    # Scene packs: curated bundles of public-domain images + an auto-built
    # scene, installable from the panel with no manual setup. Built on top
    # of the library and scene managers above, so it's set up after both.
    from .scene_packs import ScenePackManager  # noqa: PLC0415

    scene_pack_manager = ScenePackManager(hass, library_manager, scene_manager)
    await scene_pack_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_scene_packs"] = scene_pack_manager

    # Backfill provenance on scenes from packs installed before Scene.source
    # existed -- otherwise they'd show up as "User Generated" instead of
    # "Add-on" in the panel after upgrading. No-ops once every scene is tagged.
    for scene_id in scene_pack_manager.installed_scene_ids():
        await scene_manager.async_mark_scene_source(scene_id, "addon")

    from .scene_packs_http import (  # noqa: PLC0415
        FraimicScenePackInstallView,
        FraimicScenePacksView,
        FraimicScenePackSyncView,
        FraimicScenePackUninstallView,
    )

    hass.http.register_view(FraimicScenePacksView())
    hass.http.register_view(FraimicScenePackInstallView())
    hass.http.register_view(FraimicScenePackSyncView())
    hass.http.register_view(FraimicScenePackUninstallView())

    # One-off cleanup: quote_of_the_day/scripture_of_the_day are retired in
    # favour of per-instance xOTD content (see xotd.py). Their widget
    # uninstall path never looks the pack_id up in the (now-pruned)
    # catalog, so this is safe to run unconditionally even after the
    # catalog entries are gone -- self-heals on upgrade, no user action
    # required.
    from .scene_packs import ScenePackError  # noqa: PLC0415

    for _legacy_pack_id in ("quote_of_the_day", "scripture_of_the_day"):
        try:
            await scene_pack_manager.async_uninstall_pack(_legacy_pack_id)
            _LOGGER.info("Removed legacy add-on '%s' (replaced by xOTD)", _legacy_pack_id)
        except ScenePackError:
            pass  # not installed, nothing to do

    # Skills: frame-agnostic, on-demand-renderable content presets (Word of
    # the Day, Joke of the Day, ...) -- the frame-agnostic counterpart to a
    # library image_id. Built on the library and scene-pack managers above
    # (needs the library for image-mode upload/list, and the scene-pack
    # manager for the "xotd" catalog entry's script_url/config_schema).
    from .skills import SkillManager  # noqa: PLC0415

    skill_manager = SkillManager(hass, library_manager, scene_pack_manager)
    await skill_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_skills"] = skill_manager

    from .skills_http import (  # noqa: PLC0415
        FraimicSkillSendView,
        FraimicSkillsView,
        FraimicSkillView,
    )

    hass.http.register_view(FraimicSkillsView())
    hass.http.register_view(FraimicSkillView())
    hass.http.register_view(FraimicSkillSendView())

    # One-time migration: xOTD's old per-instance (content_mode, frame,
    # schedule) model is retired in favour of frame-agnostic skills
    # scheduled through the general ScheduleManager. Reads the old storage
    # key directly (rather than importing the retired xotd.py) and clears
    # it once done, so this is a no-op on every subsequent restart.
    await _async_migrate_xotd_instances(hass, skill_manager, schedule_manager)

    # Auto-create the device-less "scenes hub" entry (hosts scene.* entities
    # for voice control) if it doesn't exist yet -- self-heals on upgrade,
    # no user action required.
    has_hub = any(
        entry.data.get("kind") == KIND_SCENES_HUB
        for entry in hass.config_entries.async_entries(DOMAIN)
    )
    if not has_hub:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={"kind": KIND_SCENES_HUB},
            )
        )

    # Periodic background subnet scan → HA's standard discovery pipeline.
    # Registered here (not per-entry) so new frames surface even before the
    # first one is configured.
    from .discovery import async_setup_discovery  # noqa: PLC0415

    async_setup_discovery(hass)

    # Inject the Lovelace card JS so it's available on any dashboard.
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

    add_extra_js_url(hass, f"/fraimic/fraimic-card.js?v={_cache_bust}")

    # Register the "Frames" sidebar panel.
    from homeassistant.components.panel_custom import async_register_panel  # noqa: PLC0415

    await async_register_panel(
        hass,
        webcomponent_name="fraimic-panel",
        frontend_url_path=_PANEL_PATH,
        sidebar_title=_PANEL_SIDEBAR_TITLE,
        sidebar_icon=_PANEL_SIDEBAR_ICON,
        module_url=f"{_PANEL_URL}?v={_cache_bust}",
        embed_iframe=False,
        require_admin=False,
        config={},
    )

    return True


# ---------------------------------------------------------------------------
# Integration setup / teardown (per config entry)
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: "ConfigEntry") -> bool:
    """Set up a Fraimic frame from a config entry."""

    if entry.data.get("kind") == KIND_SCENES_HUB:
        # Device-less entry: no coordinator, just hosts the scene entities.
        await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
        if not hass.services.has_service(DOMAIN, "send_image"):
            _register_services(hass)
        return True

    from .const import CONF_DRIVER, DRIVER_MEURAL, DRIVER_SAMSUNG  # noqa: PLC0415

    if entry.data.get(CONF_DRIVER) == DRIVER_MEURAL:
        from .meural_coordinator import MeuralCoordinator  # noqa: PLC0415

        coordinator = MeuralCoordinator(hass, entry)
    elif entry.data.get(CONF_DRIVER) == DRIVER_SAMSUNG:
        from .samsung_coordinator import SamsungCoordinator  # noqa: PLC0415

        coordinator = SamsungCoordinator(hass, entry)
    else:
        coordinator = FraimicCoordinator(hass, entry)

    # Hydrate the Frames panel thumbnail hint from disk before anything else
    # can query it, so a restart doesn't drop back to the generic icon until
    # the next send.
    await coordinator.async_load_last_image()

    # Hydrate any send that was still queued (frame asleep) when Home
    # Assistant last stopped, before the first refresh, so a restart never
    # drops it. (MeuralCoordinator no-ops this.)
    await coordinator.async_load_pending_send()

    # Register the coordinator *before* first_refresh / platforms so send
    # resolution never races an empty hass.data slot, and so a soft options
    # update can find it without a full reload.
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = coordinator
    domain_data[f"_options_snapshot_{entry.entry_id}"] = dict(entry.options)

    # First data fetch. Fraimic raises ConfigEntryNotReady when offline
    # (HA retries). Meural/Samsung soft-fail so the coordinator stays loaded
    # for send resolution even if the panel is asleep during startup.
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        driver = entry.data.get("driver") or "fraimic"
        if driver in ("meural", "samsung"):
            _LOGGER.warning(
                "Initial poll for %s frame %s failed; keeping entry loaded for send",
                driver,
                entry.title,
            )
        else:
            domain_data.pop(entry.entry_id, None)
            domain_data.pop(f"_options_snapshot_{entry.entry_id}", None)
            raise

    # Every configured frame is guaranteed a spot on the default wall --
    # this hook covers embedded adds, discovery adds, and plain restarts.
    wall_manager = hass.data[DOMAIN].get("_walls")
    if wall_manager is not None:
        await wall_manager.async_ensure_placement(entry)

    # Keep the coordinator in sync if DHCP discovery updates the host
    # in entry.data without triggering a full reload.
    entry.async_on_unload(
        entry.add_update_listener(coordinator.async_config_entry_updated)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (only for the first entry; subsequent entries
    # reuse the same service handlers).
    if not hass.services.has_service(DOMAIN, "send_image"):
        _register_services(hass)

    # Soft options listener: orientation locks must NOT reload the entry
    # (that dropped Meural coordinators while entity registry rows remained).
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: "ConfigEntry") -> bool:
    """Unload a Fraimic config entry."""

    if entry.data.get("kind") == KIND_SCENES_HUB:
        return await hass.config_entries.async_unload_platforms(entry, HUB_PLATFORMS)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Domain-level state (the shared library, keyed "_library") lives
        # independently of any single frame's config entry, so don't tear
        # the whole domain dict down just because it's the only thing left.
        remaining_frame_entries = [
            key for key in hass.data[DOMAIN] if not key.startswith("_")
        ]
        if not remaining_frame_entries:
            # Remove services when the last frame entry is gone.
            for service in (
                "send_image", "send_scene", "send_skill", "refresh",
                "sleep", "wake", "restart",
            ):
                hass.services.async_remove(DOMAIN, service)
            
            # Clean up active widget timers!
            scene_packs = hass.data[DOMAIN].get("_scene_packs")
            if scene_packs:
                scene_packs.unload()

            # ... and every armed schedule timer.
            schedules = hass.data[DOMAIN].get("_schedules")
            if schedules:
                schedules.unload()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: "ConfigEntry") -> None:
    """Clean up when a frame's config entry is deleted (not just unloaded):
    drop its placement from every wall, or removed frames haunt wall
    layouts forever (CODE_REVIEW #28)."""
    if entry.data.get("kind") == KIND_SCENES_HUB:
        return
    wall_manager = hass.data.get(DOMAIN, {}).get("_walls")
    if wall_manager is not None:
        await wall_manager.async_prune_entry(entry.entry_id)


# Options that require a full config-entry reload (coordinator interval, etc.).
_RELOAD_OPTION_KEYS = frozenset({"scan_interval"})


async def _async_update_listener(hass: HomeAssistant, entry: "ConfigEntry") -> None:
    """Handle config entry option updates.

    Only *scan_interval* forces a full reload. Orientation locks are applied
    at send time from entry.options / live gsensor — rewriting them used to
    call async_reload, which unloaded the Meural coordinator while entity
    registry rows stayed, so library send failed with "No frame coordinator".
    """
    from .const import (  # noqa: PLC0415
        CONF_ORIENTATION,
        CONF_ORIENTATION_FOLLOW_DEVICE,
    )
    from .http_api import _is_frame_coordinator  # noqa: PLC0415

    domain_data = hass.data.setdefault(DOMAIN, {})
    snap_key = f"_options_snapshot_{entry.entry_id}"
    prev = domain_data.get(snap_key)
    curr = dict(entry.options)
    domain_data[snap_key] = curr

    if prev is None:
        return

    if any(prev.get(k) != curr.get(k) for k in _RELOAD_OPTION_KEYS):
        await hass.config_entries.async_reload(entry.entry_id)
        return

    orient_changed = prev.get(CONF_ORIENTATION) != curr.get(
        CONF_ORIENTATION
    ) or prev.get(CONF_ORIENTATION_FOLLOW_DEVICE) != curr.get(
        CONF_ORIENTATION_FOLLOW_DEVICE
    )
    coord = domain_data.get(entry.entry_id)
    if orient_changed and _is_frame_coordinator(coord):
        redisplay = getattr(coord, "async_redisplay_last", None)
        if callable(redisplay):
            await redisplay()


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def _get_coordinator_by_device_id(
    hass: HomeAssistant, device_id: str
) -> tuple[Any, str]:
    """Return (coordinator, entry_id) for the given device_id, or raise."""
    from .http_api import _is_frame_coordinator  # noqa: PLC0415

    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)
    if device_entry is None:
        raise HomeAssistantError(f"Device '{device_id}' not found in device registry")

    domain_data: dict = hass.data.get(DOMAIN, {})
    for entry_id in device_entry.config_entries:
        coord = domain_data.get(entry_id)
        if _is_frame_coordinator(coord):
            return coord, entry_id

    raise HomeAssistantError(
        f"No frame coordinator found for device '{device_id}'"
    )


def _safe_media_join(local_dir: str, relative: str) -> str:
    """Join *relative* onto *local_dir*, rejecting any escape via '..' or an
    absolute path override (os.path.join discards local_dir if relative is
    absolute).

    Deliberately uses abspath/normpath rather than realpath: it must reject
    '../' segments that escape local_dir, but must NOT reject a legitimate
    symlink inside local_dir that points elsewhere on disk (e.g. a large
    photo library mounted outside the HA config directory) -- realpath would
    resolve that symlink and then wrongly flag it as outside local_dir.
    """
    joined = os.path.normpath(os.path.join(local_dir, relative))
    base = os.path.abspath(local_dir)
    if joined != base and not joined.startswith(base + os.sep):
        raise HomeAssistantError(f"Invalid media path: {relative}")
    return joined


async def _fetch_media_bytes(hass: HomeAssistant, url: str) -> bytes:
    """Fetch a media source's (possibly relative, unsigned) HTTP URL."""
    from homeassistant.components.http.auth import async_sign_path  # noqa: PLC0415
    from homeassistant.helpers.aiohttp_client import (  # noqa: PLC0415
        async_get_clientsession,
    )
    from homeassistant.helpers.network import get_url  # noqa: PLC0415

    if url.startswith("/"):
        signed_path = async_sign_path(hass, url, timedelta(seconds=30))
        url = get_url(hass) + signed_path

    session = async_get_clientsession(hass)
    async with session.get(url) as resp:
        if resp.status != 200:
            raise HomeAssistantError(
                f"Failed to download media from {url}: HTTP {resp.status}"
            )
        return await resp.read()


async def _download_media_to_temp(
    hass: HomeAssistant, url: str, mime_type: str | None
) -> str:
    """Download a media source's HTTP-only URL (e.g. an ai_task-generated
    image) to a temp file, since those sources don't expose a filesystem path.
    """
    data = await _fetch_media_bytes(hass, url)
    suffix = mimetypes.guess_extension(mime_type or "") or ".tmp"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


async def _resolve_media_path(
    hass: HomeAssistant, media_content_id: str
) -> tuple[str, bool]:
    """Resolve a media content_id or path string to an absolute filesystem path.

    Returns (path, is_temp) -- is_temp is True when the caller owns a
    downloaded temp file and must clean it up after use.
    """
    if media_content_id.startswith("media-source://"):
        try:
            from homeassistant.components.media_source import (  # noqa: PLC0415
                async_resolve_media,
            )

            media_item = await async_resolve_media(hass, media_content_id, None)
            url: str = media_item.url

            prefix = "/media/local/"
            if url.startswith(prefix):
                local_dir = hass.config.media_dirs.get(
                    "local", hass.config.path("media")
                )
                return _safe_media_join(local_dir, url[len(prefix):]), False

            return (
                await _download_media_to_temp(hass, url, media_item.mime_type),
                True,
            )
        except ImportError as err:
            raise HomeAssistantError(
                "media_source component is not available"
            ) from err

    if media_content_id.startswith("/media/"):
        local_dir = hass.config.media_dirs.get("local", hass.config.path("media"))
        return _safe_media_join(local_dir, media_content_id[len("/media/"):]), False

    return media_content_id, False


def _find_ai_task_image_entity(hass: HomeAssistant) -> str:
    """Return the first ai_task entity that supports image generation."""
    for state in hass.states.async_all("ai_task"):
        if state.attributes.get("supported_features", 0) & _AI_TASK_GENERATE_IMAGE_FEATURE:
            return state.entity_id
    raise HomeAssistantError(
        "No AI Task entity with image-generation support is configured "
        "(set up an AI Task-capable conversation agent first)"
    )


async def _async_migrate_xotd_instances(hass: HomeAssistant, skill_manager, schedule_manager) -> None:
    """One-time migration off the retired per-instance xOTD model.

    Reads the old `fraimic_xotd` storage key directly (the retired xotd.py's
    `XotdInstance`/`XotdManager` classes are gone, so this doesn't import
    them) and converts each instance 1:1 into a Skill (content_mode +
    config, no frame/schedule) plus a Schedule with a "skill" action --
    deliberately no content-based dedup, so a user's distinct instances stay
    distinct and traceable after upgrade. Clears the old store once done,
    which makes this naturally a no-op on every subsequent restart.
    """
    from homeassistant.helpers.storage import Store  # noqa: PLC0415

    from .schedules import ScheduleError  # noqa: PLC0415
    from .skills import SkillError  # noqa: PLC0415

    store = Store(hass, 1, f"{DOMAIN}_xotd")
    stored = await store.async_load()
    instances = (stored or {}).get("instances") or []
    if not instances:
        return

    for data in instances:
        instance_id = data.get("instance_id", "?")
        content_mode = data.get("content_mode")
        frame_id = data.get("frame_id")
        old_trigger = data.get("schedule") or {"type": "hourly"}
        mode_config = data.get("mode_config") or {}
        if not content_mode or not frame_id:
            _LOGGER.warning("Skipping malformed stored xOTD instance: %s", data)
            continue

        if content_mode == "image":
            sub_mode = mode_config.get("sub_mode")
            if sub_mode not in ("image_feed", "image_album"):
                _LOGGER.warning(
                    "Skipping xOTD instance '%s' with unrecognised image sub_mode %r",
                    instance_id, sub_mode,
                )
                continue
            skill_content_mode = sub_mode
            skill_config = {k: v for k, v in mode_config.items() if k != "sub_mode"}
        else:
            skill_content_mode = content_mode
            skill_config = mode_config

        label = f"{skill_content_mode.replace('_', ' ').title()} (migrated)"
        try:
            skill = await skill_manager.async_save_skill(label, skill_content_mode, skill_config)
        except SkillError as err:
            _LOGGER.warning("Failed to migrate xOTD instance '%s': %s", instance_id, err)
            continue

        if old_trigger.get("type") == "hourly":
            trigger = {"type": "recurring", "freq": "hourly"}
        else:
            # xOTD daily times are HH:MM:SS; ScheduleManager's recurring
            # trigger takes HH:MM -- truncating seconds is lossless in
            # practice since the old UI only ever offered :00 seconds.
            time_str = str(old_trigger.get("time", "07:00:00"))
            trigger = {"type": "recurring", "freq": "daily", "time": time_str[:5]}

        action = {"type": "skill", "entry_id": frame_id, "skill_id": skill["skill_id"]}
        try:
            await schedule_manager.async_create_schedule(
                label, action, trigger, enabled=bool(data.get("enabled", True))
            )
        except ScheduleError as err:
            _LOGGER.warning(
                "Migrated skill '%s' but couldn't recreate its schedule: %s",
                skill["skill_id"], err,
            )

    await store.async_save({"enabled": False, "instances": []})
    _LOGGER.info("Migrated %d xOTD instance(s) to skills + schedules", len(instances))


def _register_services(hass: HomeAssistant) -> None:
    """Register all Fraimic services."""

    async def _handle_restart(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_RESTART)
        _LOGGER.info("Restart command sent to frame %s", coordinator.host)

    async def _handle_sleep(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_SLEEP)
        _LOGGER.info("Sleep command sent to frame %s", coordinator.host)

    async def _handle_wake(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        # Meural maps /api/wake → resume; Fraimic has no wake endpoint.
        if hasattr(coordinator, "async_resume"):
            await coordinator.async_resume()
        else:
            raise HomeAssistantError(
                "Wake is only supported on Meural Canvas frames"
            )
        _LOGGER.info("Wake command sent to frame %s", coordinator.host)

    async def _handle_refresh(call: ServiceCall) -> None:
        coordinator, _ = _get_coordinator_by_device_id(hass, call.data["device_id"])
        await coordinator.async_send_command(API_REFRESH)
        _LOGGER.info("Refresh command sent to frame %s", coordinator.host)

    async def _handle_send_image(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        media_content_id: str = call.data["media_content_id"]

        coordinator, entry_id = _get_coordinator_by_device_id(hass, device_id)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")

        from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

        spec = render_spec_for_hass_entry(hass, entry)

        abs_path, is_temp = await _resolve_media_path(hass, media_content_id)

        if not os.path.isfile(abs_path):
            raise HomeAssistantError(f"Media file not found: {abs_path}")

        from .panel_codec import (  # noqa: PLC0415
            encode_path_for_panel_with_preview,
            panel_codec_for_entry,
        )

        try:
            codec_id = panel_codec_for_entry(entry).id
        except ValueError:
            codec_id = None

        try:
            try:
                image_bytes, preview_bytes = await hass.async_add_executor_job(
                    encode_path_for_panel_with_preview,
                    abs_path,
                    spec.width,
                    spec.height,
                    spec.rotation,
                    spec.locked,
                    codec_id,
                )
            except Exception as err:  # noqa: BLE001
                raise HomeAssistantError(
                    f"Failed to convert image '{abs_path}': {err}"
                ) from err
        finally:
            if is_temp:
                os.remove(abs_path)

        # async_send_image_or_queue already updates the Frames panel's
        # thumbnail hint (last_thumbnail, since this service resolves a
        # media_content_id rather than a Library image_id) on success; on a
        # sleeping/unreachable frame it queues the image instead of raising,
        # so this call doesn't fail just because the frame is asleep.
        result = await coordinator.async_send_image_or_queue(
            image_bytes, thumbnail=preview_bytes
        )

        if result["queued"]:
            _LOGGER.info(
                "Frame %s unreachable — image '%s' queued for delivery on wake",
                coordinator.host,
                abs_path,
            )
        else:
            _LOGGER.info(
                "Image '%s' (%dx%d) sent to frame %s",
                abs_path,
                spec.width,
                spec.height,
                coordinator.host,
            )

    async def _handle_generate_ai_image(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        prompt: str = call.data["prompt"]
        ai_task_entity_id: str | None = call.data.get("ai_task_entity_id")

        coordinator, entry_id = _get_coordinator_by_device_id(hass, device_id)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")

        from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

        spec = render_spec_for_hass_entry(hass, entry)

        if not ai_task_entity_id:
            ai_task_entity_id = _find_ai_task_image_entity(hass)

        gen_result = await hass.services.async_call(
            "ai_task",
            "generate_image",
            {
                "entity_id": ai_task_entity_id,
                "task_name": "Fraimic AI-generated frame image",
                "instructions": prompt,
            },
            blocking=True,
            return_response=True,
        )

        from homeassistant.components.media_source import (  # noqa: PLC0415
            async_resolve_media,
        )

        media_item = await async_resolve_media(
            hass, gen_result["media_source_id"], None
        )
        raw_bytes = await _fetch_media_bytes(hass, media_item.url)

        manager = hass.data.get(DOMAIN, {}).get("_library")
        if manager is None:
            raise HomeAssistantError("Library manager not initialised")

        import uuid  # noqa: PLC0415

        filename = f"genai_{uuid.uuid4().hex[:8]}.png"
        record = await manager.async_upload(filename, raw_bytes, [AI_GENERATED_ALBUM])
        image_id = record["image_id"]

        from .panel_codec import panel_codec_for_entry  # noqa: PLC0415

        try:
            codec_id = panel_codec_for_entry(entry).id
        except ValueError:
            codec_id = None
        bin_bytes = await manager.async_get_bin_for_send(
            image_id, spec, codec_id=codec_id
        )
        result = await coordinator.async_send_image_or_queue(
            bin_bytes, image_id=image_id
        )

        if result["queued"]:
            _LOGGER.info(
                "AI-generated image '%s' queued for frame %s (asleep)",
                image_id,
                coordinator.host,
            )
        else:
            _LOGGER.info(
                "AI-generated image '%s' sent to frame %s", image_id, coordinator.host
            )

    async def _handle_send_scene(call: ServiceCall) -> None:
        name: str = call.data["name"]

        scene_manager = hass.data.get(DOMAIN, {}).get("_scenes")
        if scene_manager is None:
            raise HomeAssistantError("Scene manager not initialised")

        scene = await scene_manager.async_get_scene_by_name(name)
        if scene is None:
            raise HomeAssistantError(f"Scene '{name}' not found")

        result = await scene_manager.async_send_scene(hass, scene.scene_id)
        results = result["results"]
        # A queued mapping (frame asleep) isn't a failure -- it'll be
        # delivered once the frame wakes -- so only count real failures here.
        failures = [
            r for r in results if not r.get("success") and not r.get("queued")
        ]
        queued = [r for r in results if r.get("queued")]

        if failures and len(failures) == len(results):
            # Every mapping failed -- raise so the calling automation/script
            # sees this as an error rather than a silent no-op success.
            raise HomeAssistantError(
                f"Scene '{name}' failed to send to any frame: {failures}"
            )
        if failures:
            _LOGGER.warning(
                "Scene '%s' sent with %d failure(s): %s", name, len(failures), failures
            )
        else:
            _LOGGER.info("Scene '%s' sent to %d frame(s)", name, len(results))
        if queued:
            _LOGGER.info(
                "Scene '%s': %d frame(s) asleep, image queued for delivery on wake",
                name,
                len(queued),
            )

    hass.services.async_register(
        DOMAIN, "restart", _handle_restart, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "sleep", _handle_sleep, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "wake", _handle_wake, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "refresh", _handle_refresh, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "send_image", _handle_send_image, schema=_SEND_IMAGE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "send_scene", _handle_send_scene, schema=_SEND_SCENE_SCHEMA
    )
    async def _handle_send_skill(call: ServiceCall) -> None:
        device_id: str = call.data["device_id"]
        skill_id: str = call.data["skill_id"]

        _, entry_id = _get_coordinator_by_device_id(hass, device_id)

        scene_manager = hass.data.get(DOMAIN, {}).get("_scenes")
        if scene_manager is None:
            raise HomeAssistantError("Scene manager not initialised")

        from .scenes import unwrap_single_result  # noqa: PLC0415

        result = await scene_manager.async_send_mappings(
            hass, {entry_id: {"type": "skill", "skill_id": skill_id}}
        )
        outcome = unwrap_single_result(result)

        if outcome.get("success"):
            _LOGGER.info("Skill '%s' sent to device %s", skill_id, device_id)
        elif outcome.get("queued"):
            # Frame asleep/unreachable -- delivered automatically on wake,
            # same as send_image/generate_ai_image queuing; not an error.
            _LOGGER.info(
                "Skill '%s' queued for device %s (frame asleep)", skill_id, device_id
            )
        else:
            raise HomeAssistantError(
                outcome.get("message") or f"Failed to send skill '{skill_id}'"
            )

    hass.services.async_register(
        DOMAIN,
        "generate_ai_image",
        _handle_generate_ai_image,
        schema=_GENERATE_AI_IMAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "send_skill", _handle_send_skill, schema=_SEND_SKILL_SCHEMA
    )

    async def _handle_auto_tag_all(call: ServiceCall) -> None:
        overwrite: bool = call.data.get("overwrite", False)
        manager = hass.data.get(DOMAIN, {}).get("_library")
        if manager is None:
            raise HomeAssistantError("Library manager not initialised")

        images = await manager.async_list_images()
        count = 0
        for img in images:
            image_id = img.get("image_id")
            if not image_id:
                continue
            if not overwrite and img.get("tags"):
                continue
            manager._schedule_auto_tagging(image_id, force=True)
            count += 1

        _LOGGER.info("Scheduled AI auto-tagging for %d library images", count)

    hass.services.async_register(
        DOMAIN,
        "auto_tag_all",
        _handle_auto_tag_all,
        schema=vol.Schema({vol.Optional("overwrite", default=False): bool}),
    )
