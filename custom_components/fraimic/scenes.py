"""Scenes: named (frame, image) assignment lists that can be sent all at
once -- e.g. four frames on a wall each showing a different image, sent
together as one action.

A scene maps a config entry_id (the frame) to a library image_id. Config
entries only exist on this Home Assistant instance, so scenes are pure local
state -- there's no reason to replicate them across the shared library's
storage backends (Local/Dropbox/Google Drive) the way images are.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGNAL_SCENES_UPDATED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_STORAGE_KEY = f"{DOMAIN}_scenes"
_STORAGE_VERSION = 1


class SceneError(Exception):
    """Raised for invalid scene operations (bad name, empty mappings, not found)."""


@dataclass
class Scene:
    """A named set of (frame entry_id -> library image_id) assignments."""

    scene_id: str
    name: str
    mappings: dict[str, str] = field(default_factory=dict)
    created_at: float = 0.0
    # Which album the editor was scoped to when this scene was built. Purely
    # a UI convenience for reopening the editor pre-scoped -- sending a scene
    # never consults this, since mappings already carry the resolved image_ids.
    album: str | None = None
    # "user" (built by hand in the editor) or "addon" (auto-created by a
    # scene pack install, see scene_packs.py). Purely descriptive -- the
    # Scenes tab uses it to group cards, sending never consults it.
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "mappings": self.mappings,
            "created_at": self.created_at,
            "album": self.album,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        return cls(
            scene_id=data["scene_id"],
            name=data["name"],
            mappings=dict(data.get("mappings") or {}),
            created_at=data.get("created_at", 0.0),
            album=data.get("album"),
            source=data.get("source") or "user",
        )


class SceneManager:
    """Owns the set of user-defined scenes."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._scenes: dict[str, Scene] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        for data in (stored or {}).get("scenes", []):
            scene = Scene.from_dict(data)
            self._scenes[scene.scene_id] = scene

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"scenes": [scene.to_dict() for scene in self._scenes.values()]}
        )

    @property
    def scenes(self) -> dict[str, Scene]:
        """Synchronous read-only view, for the scene entity platform."""
        return self._scenes

    async def async_list_scenes(self) -> list[dict[str, Any]]:
        return [scene.to_dict() for scene in self._scenes.values()]

    async def async_get_scene(self, scene_id: str) -> Scene | None:
        return self._scenes.get(scene_id)

    async def async_get_scene_by_name(self, name: str) -> Scene | None:
        name = (name or "").strip().lower()
        for scene in self._scenes.values():
            if scene.name.strip().lower() == name:
                return scene
        return None

    async def async_save_scene(
        self,
        name: str,
        mappings: dict[str, str],
        scene_id: str | None = None,
        album: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        """Create a new scene (scene_id=None) or update an existing one."""
        name = (name or "").strip()
        if not name:
            raise SceneError("Scene name can't be empty")

        mappings = {
            entry_id: image_id
            for entry_id, image_id in (mappings or {}).items()
            if entry_id and image_id
        }
        if not mappings:
            raise SceneError("A scene needs at least one frame/image assignment")

        if scene_id is not None and scene_id not in self._scenes:
            # Updating a scene that's gone (e.g. deleted from another tab
            # since this edit was opened) must fail, not silently resurrect
            # it under its old id with whatever's in this stale form.
            raise SceneError(f"Scene '{scene_id}' not found")

        existing_by_name = await self.async_get_scene_by_name(name)
        if existing_by_name is not None and existing_by_name.scene_id != scene_id:
            raise SceneError(f"A scene named '{name}' already exists")

        if scene_id is not None:
            scene = self._scenes[scene_id]
            scene.name = name
            scene.mappings = mappings
            scene.album = album
            # source deliberately untouched -- editing a scene shouldn't
            # reclassify a pack-created scene as user-made or vice versa.
        else:
            scene = Scene(
                scene_id=uuid.uuid4().hex[:12],
                name=name,
                mappings=mappings,
                created_at=time.time(),
                album=album,
                source=source,
            )
            self._scenes[scene.scene_id] = scene

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_SCENES_UPDATED)
        return scene.to_dict()

    async def async_delete_scene(self, scene_id: str) -> None:
        if scene_id in self._scenes:
            del self._scenes[scene_id]
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_SCENES_UPDATED)
            # Any schedule pointing at this scene is now broken: disable it
            # and mark it target_missing so the calendar popup shows the
            # user what broke instead of erroring at fire time.
            schedule_manager = self.hass.data.get(DOMAIN, {}).get("_schedules")
            if schedule_manager is not None:
                await schedule_manager.async_handle_scene_deleted(scene_id)

    async def async_mark_scene_source(self, scene_id: str, source: str) -> None:
        """Backfill a scene's provenance without touching its content or
        firing SIGNAL_SCENES_UPDATED -- used only for the startup migration
        that reclassifies scenes from packs installed before Scene.source
        existed (see ScenePackManager.installed_scene_ids)."""
        scene = self._scenes.get(scene_id)
        if scene is not None and scene.source != source:
            scene.source = source
            await self._async_persist()

    async def async_send_scene(
        self, hass: "HomeAssistant", scene_id: str
    ) -> dict[str, Any]:
        """Send every image in a scene to its assigned frame."""
        scene = self._scenes.get(scene_id)
        if scene is None:
            raise SceneError(f"Scene '{scene_id}' not found")
        return await self.async_send_mappings(hass, scene.mappings)

    async def async_send_mappings(
        self, hass: "HomeAssistant", mappings: dict[str, str]
    ) -> dict[str, Any]:
        """Send each (frame entry_id -> library image_id) assignment.

        The single executor for every multi-frame (or scheduled) send in
        the integration: scene sends, and fired schedules (scenes.py has no
        knowledge of schedules -- schedules.py calls down into this), all
        terminate here. Keep it the only place this fan-out logic lives.

        Each mapping is independent -- a frame that's been removed or an
        image that's been deleted since the mapping was created only fails
        that one mapping, not the whole send.

        Two phases, each internally concurrent: every mapping's .bin is
        resolved first (cache lookup, or original fetch + conversion when
        cold), then every frame upload fires together -- resolving fully
        before uploading anything is what makes the frames update together
        even when some bins are cold and others cached. Concurrent
        resolution is safe: the only shared state it touches is the
        manifest update inside async_save_bin, and every backend wraps that
        read-modify-write in its _manifest_lock.
        """
        library_manager = hass.data.get(DOMAIN, {}).get("_library")
        if library_manager is None:
            raise SceneError("Library manager not initialised")

        from .helpers import render_spec_for_entry  # noqa: PLC0415

        prepared: dict[str, tuple[Any, bytes, str]] = {}
        results: list[dict[str, Any]] = []

        async def _prepare_one(entry_id: str, image_id: str) -> dict[str, Any] | None:
            """Resolve one mapping's bin; returns a failure record, or None
            after stashing the ready-to-send bytes in `prepared`."""
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                return {
                    "entry_id": entry_id,
                    "success": False,
                    "message": "Frame is no longer configured",
                }
            coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
            if coordinator is None:
                return {
                    "entry_id": entry_id,
                    "success": False,
                    "message": "Frame coordinator not available",
                }
            try:
                bin_bytes = await library_manager.async_get_bin_for_send(
                    image_id, render_spec_for_entry(entry)
                )
            except Exception as err:  # noqa: BLE001
                return {"entry_id": entry_id, "success": False, "message": str(err)}
            prepared[entry_id] = (coordinator, bin_bytes, image_id)
            return None

        failures = await asyncio.gather(
            *(
                _prepare_one(entry_id, image_id)
                for entry_id, image_id in mappings.items()
            )
        )
        results.extend(failure for failure in failures if failure is not None)

        async def _send_one(coordinator: Any, bin_bytes: bytes, image_id: str) -> dict[str, Any]:
            # async_send_image_or_queue queues (rather than raising) if the
            # frame is asleep/unreachable, and already updates last_image_id
            # on immediate success -- see FraimicCoordinator.
            return await coordinator.async_send_image_or_queue(bin_bytes, image_id=image_id)

        sent = await asyncio.gather(
            *(
                _send_one(coordinator, bin_bytes, image_id)
                for coordinator, bin_bytes, image_id in prepared.values()
            ),
            return_exceptions=True,
        )
        for entry_id, outcome in zip(prepared.keys(), sent):
            if isinstance(outcome, BaseException):
                results.append({"entry_id": entry_id, "success": False, "message": str(outcome)})
            elif outcome["queued"]:
                results.append({"entry_id": entry_id, "success": False, "queued": True})
            else:
                results.append({"entry_id": entry_id, "success": True})

        return {"results": results}
