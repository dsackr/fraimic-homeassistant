"""Scene platform for the Fraimic integration.

Hosted on the auto-created "scenes hub" config entry (see
const.KIND_SCENES_HUB and __init__.py) rather than any single frame's entry,
since scenes are domain-level state shared across every frame -- forwarding
this platform from a frame's own entry would register the same scene
unique_ids from every frame, and deleting whichever frame happened to win
entity ownership would silently drop every scene entity.

Exposing scenes as real scene.* entities (instead of only the fraim.send_scene
service) is what lets Alexa/Google Assistant/Assist activate them by name --
HA's voice integrations act on entities, not arbitrary services.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.scene import Scene as SceneEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_SCENES_UPDATED

if TYPE_CHECKING:
    from .scenes import Scene as FraimicScene
    from .scenes import SceneManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fraimic scene entities from the scenes hub config entry."""
    manager: SceneManager = hass.data[DOMAIN]["_scenes"]
    entities: dict[str, FraimicSceneEntity] = {}

    @callback
    def _sync() -> None:
        current = manager.scenes  # {scene_id: Scene}, kept live by SceneManager

        new_entities = [
            FraimicSceneEntity(manager, entry, scene)
            for scene_id, scene in current.items()
            if scene_id not in entities
        ]
        for scene_entity in new_entities:
            entities[scene_entity.scene_id] = scene_entity
        if new_entities:
            async_add_entities(new_entities)

        stale_ids = [sid for sid in entities if sid not in current]
        if stale_ids:
            ent_reg = er.async_get(hass)
            for scene_id in stale_ids:
                removed = entities.pop(scene_id)
                if removed.entity_id and ent_reg.async_get(removed.entity_id):
                    ent_reg.async_remove(removed.entity_id)
                else:
                    hass.async_create_task(removed.async_remove())

        for scene_id, scene in current.items():
            existing = entities.get(scene_id)
            if existing is not None:
                existing.refresh(scene)

    _sync()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_SCENES_UPDATED, _sync)
    )


class FraimicSceneEntity(SceneEntity):
    """A Fraimic scene, exposed as a native scene.* entity for voice control."""

    _attr_should_poll = False

    def __init__(
        self,
        manager: SceneManager,
        entry: ConfigEntry,
        scene: FraimicScene,
    ) -> None:
        """Initialise."""
        self._manager = manager
        self._entry = entry
        self.scene_id = scene.scene_id
        self._attr_unique_id = f"fraimic_scene_{scene.scene_id}"
        self._attr_name = scene.name

    @property
    def device_info(self) -> DeviceInfo:
        """Group every scene under one virtual "Fraimic Scenes" device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Fraimic Scenes",
            manufacturer="Fraimic",
            model="Scene Hub",
        )

    def refresh(self, scene: FraimicScene) -> None:
        """Update this entity's displayed name after the scene was renamed."""
        if self._attr_name != scene.name:
            self._attr_name = scene.name
            if self.hass is not None:
                self.async_write_ha_state()

    async def async_activate(self, **kwargs: Any) -> None:
        """Send every image in this scene to its assigned frame."""
        result = await self._manager.async_send_scene(self.hass, self.scene_id)
        results = result["results"]
        failures = [r for r in results if not r.get("success")]

        if failures and len(failures) == len(results):
            raise HomeAssistantError(
                f"Scene '{self._attr_name}' failed to send to any frame: {failures}"
            )
        if failures:
            _LOGGER.warning(
                "Scene '%s' sent with %d failure(s): %s",
                self._attr_name,
                len(failures),
                failures,
            )
