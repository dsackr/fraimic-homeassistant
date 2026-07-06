"""The Fraimic integration."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

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

_SEND_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
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

    # Register the image-upload HTTP endpoint.
    from .http_api import FraimicSendImageView  # noqa: PLC0415
    hass.http.register_view(FraimicSendImageView())

    # Set up the shared image library (storage-backend agnostic) and its
    # HTTP endpoints. This is domain-level state, not per-frame, since the
    # library is shared across every configured frame.
    from .library import LibraryManager  # noqa: PLC0415

    library_manager = LibraryManager(hass)
    await library_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_library"] = library_manager

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

    # Walls: virtual layouts of a subset of the user's frames, positioned the
    # way they're physically hung. Pure panel-local state -- like scenes,
    # config entry_ids are meaningless off this HA instance, and walls are
    # never referenced by automations, voice control, or an entity platform.
    from .walls import WallManager  # noqa: PLC0415

    wall_manager = WallManager(hass)
    await wall_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_walls"] = wall_manager

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

    coordinator = FraimicCoordinator(hass, entry)

    # Hydrate the Frames panel thumbnail hint from disk before anything else
    # can query it, so a restart doesn't drop back to the generic icon until
    # the next send.
    await coordinator.async_load_last_image()

    # Perform the first data fetch; raises ConfigEntryNotReady on failure so
    # HA will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

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

    # Re-register listener so option changes (e.g. scan_interval) take effect.
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
            for service in ("send_image", "send_scene", "refresh", "sleep", "restart"):
                hass.services.async_remove(DOMAIN, service)
            
            # Clean up active widget timers!
            scene_packs = hass.data[DOMAIN].get("_scene_packs")
            if scene_packs:
                scene_packs.unload()

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: "ConfigEntry") -> None:
    """Handle config entry option updates (e.g. scan_interval changes)."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def _get_coordinator_by_device_id(
    hass: HomeAssistant, device_id: str
) -> tuple[FraimicCoordinator, str]:
    """Return (coordinator, entry_id) for the given device_id, or raise."""
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)
    if device_entry is None:
        raise HomeAssistantError(f"Device '{device_id}' not found in device registry")

    domain_data: dict[str, FraimicCoordinator] = hass.data.get(DOMAIN, {})
    for entry_id in device_entry.config_entries:
        if entry_id in domain_data:
            return domain_data[entry_id], entry_id

    raise HomeAssistantError(
        f"No Fraimic coordinator found for device '{device_id}'"
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


async def _resolve_media_path(hass: HomeAssistant, media_content_id: str) -> str:
    """Resolve a media content_id or path string to an absolute filesystem path."""
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
                return _safe_media_join(local_dir, url[len(prefix):])

            raise HomeAssistantError(f"Cannot access non-local media URL: {url}")
        except ImportError as err:
            raise HomeAssistantError(
                "media_source component is not available"
            ) from err

    if media_content_id.startswith("/media/"):
        local_dir = hass.config.media_dirs.get("local", hass.config.path("media"))
        return _safe_media_join(local_dir, media_content_id[len("/media/"):])

    return media_content_id


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

        from .helpers import render_spec_for_entry  # noqa: PLC0415

        spec = render_spec_for_entry(entry)

        abs_path = await _resolve_media_path(hass, media_content_id)

        if not os.path.isfile(abs_path):
            raise HomeAssistantError(f"Media file not found: {abs_path}")

        from .image_converter import convert_image_with_preview  # noqa: PLC0415

        try:
            image_bytes, preview_bytes = await hass.async_add_executor_job(
                convert_image_with_preview, abs_path, spec.width, spec.height,
                spec.rotation, spec.locked,
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"Failed to convert image '{abs_path}': {err}"
            ) from err

        await coordinator.async_send_image(image_bytes)

        # Update (and persist) the Frames panel's thumbnail hint. This
        # service resolves a media_content_id, not a Library image_id, so it
        # goes through last_thumbnail rather than last_image_id.
        await coordinator.async_set_last_image(thumbnail=preview_bytes)

        _LOGGER.info(
            "Image '%s' (%dx%d) sent to frame %s",
            abs_path,
            spec.width,
            spec.height,
            coordinator.host,
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
        failures = [r for r in results if not r.get("success")]

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

    hass.services.async_register(
        DOMAIN, "restart", _handle_restart, schema=_DEVICE_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "sleep", _handle_sleep, schema=_DEVICE_ID_SCHEMA
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
