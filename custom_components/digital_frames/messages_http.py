"""HTTP API view for composing & sending a styled text message.

Endpoint:
    POST /api/digital_frames/messages/send
      body: {
        message_text: str, style: "plain"|"ad_50s"|"movie_poster",
        target: {"type": "frame", "entry_id": str}
              | {"type": "scene", "scene_id": str}
              | {"type": "wall", "wall_id": str},
        save_to_library: bool,
      }
      -> {"success": bool, "results": [...], "saved_image_id": str | None}

A message is ephemeral by design -- sending one never creates a persisted
Skill (see skills.py's async_render_message_for_entry /
async_render_message_wall_crop_for_entry, called through
SceneManager.async_send_mappings' "message"/"message_wall_crop" mapping
kinds). Only the rendered *image*, when save_to_library is set, becomes a
normal library image via LibraryManager.async_upload -- reusable/re-
sendable later exactly like any photo.

save_to_library is only meaningful for "frame" and "wall" targets, where
there's one well-defined canonical image to save. A "scene" target has no
single canonical image -- each member frame independently re-renders the
same text at its own aspect ratio -- so it's rejected with 400 here (the
compose UI should disable the checkbox for that target type).
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_STYLES = ("plain", "ad_50s", "movie_poster")
_DEFAULT_STYLE = "plain"
_MESSAGE_ALBUM = "Messages"


def _get_skill_manager(hass):
    manager = hass.data.get(DOMAIN, {}).get("_skills")
    if manager is None:
        raise RuntimeError("Skill manager not initialised")
    return manager


def _get_scene_manager(hass):
    manager = hass.data.get(DOMAIN, {}).get("_scenes")
    if manager is None:
        raise RuntimeError("Scene manager not initialised")
    return manager


def _get_wall_manager(hass):
    manager = hass.data.get(DOMAIN, {}).get("_walls")
    if manager is None:
        raise RuntimeError("Wall manager not initialised")
    return manager


def _get_library_manager(hass):
    manager = hass.data.get(DOMAIN, {}).get("_library")
    if manager is None:
        raise RuntimeError("Library manager not initialised")
    return manager


class DigitalFramesMessageSendView(HomeAssistantView):
    """Compose a styled text message and send it to a frame/scene/wall."""

    url = "/api/digital_frames/messages/send"
    name = "api:digital_frames:messages:send"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        message_text = (body.get("message_text") or "").strip()
        if not message_text:
            return self.json_message("message_text is required", status_code=400)

        style = body.get("style") or _DEFAULT_STYLE
        if style not in _STYLES:
            return self.json_message(f"Invalid style: {style!r}", status_code=400)

        target = body.get("target")
        if not isinstance(target, dict) or target.get("type") not in (
            "frame",
            "scene",
            "wall",
        ):
            return self.json_message(
                "target must be {type: frame|scene|wall, ...}", status_code=400
            )
        target_type = target["type"]
        save_to_library = bool(body.get("save_to_library"))

        if save_to_library and target_type == "scene":
            return self.json_message(
                "save_to_library isn't supported for a scene target -- each "
                "frame in a scene independently re-renders the message at "
                "its own aspect ratio, so there's no single image to save",
                status_code=400,
            )

        try:
            scene_manager = _get_scene_manager(hass)
        except RuntimeError as err:
            return self.json_message(str(err), status_code=500)

        mappings: dict[str, Any] = {}
        wall = None

        if target_type == "frame":
            entry_id = target.get("entry_id")
            if not entry_id or hass.config_entries.async_get_entry(entry_id) is None:
                return self.json_message(
                    f"Frame '{entry_id}' not found", status_code=404
                )
            mappings = {
                entry_id: {
                    "type": "message",
                    "message_text": message_text,
                    "style": style,
                }
            }

        elif target_type == "scene":
            scene_id = target.get("scene_id")
            scene = await scene_manager.async_get_scene(scene_id) if scene_id else None
            if scene is None:
                return self.json_message(f"Scene '{scene_id}' not found", status_code=404)
            if not scene.mappings:
                return self.json_message("Scene has no frames", status_code=400)
            mappings = {
                entry_id: {
                    "type": "message",
                    "message_text": message_text,
                    "style": style,
                }
                for entry_id in scene.mappings
            }

        else:  # wall
            try:
                wall_manager = _get_wall_manager(hass)
            except RuntimeError as err:
                return self.json_message(str(err), status_code=500)
            wall_id = target.get("wall_id")
            wall = await wall_manager.async_get_wall(wall_id) if wall_id else None
            if wall is None:
                return self.json_message(f"Wall '{wall_id}' not found", status_code=404)
            if not wall.placements:
                return self.json_message("Wall has no frames placed", status_code=400)

            from .wall_geometry import (  # noqa: PLC0415
                WallGeometryError,
                compute_wall_canvas_geometry,
            )

            try:
                compute_wall_canvas_geometry(hass, wall, list(wall.placements))
            except WallGeometryError as err:
                return self.json_message(str(err), status_code=400)

            mappings = {
                entry_id: {
                    "type": "message_wall_crop",
                    "message_text": message_text,
                    "style": style,
                    "wall_id": wall_id,
                }
                for entry_id in wall.placements
            }

        try:
            result = await scene_manager.async_send_mappings(hass, mappings)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to send message: %s", err)
            return self.json_message(f"Failed to send message: {err}", status_code=500)

        results = result.get("results", [])
        success = bool(results) and all(r.get("success") for r in results)

        saved_image_id = None
        if save_to_library and success:
            try:
                skill_manager = _get_skill_manager(hass)
                library_manager = _get_library_manager(hass)

                if target_type == "frame":
                    from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

                    entry = hass.config_entries.async_get_entry(target["entry_id"])
                    spec = render_spec_for_hass_entry(hass, entry)
                    width, height = spec.width, spec.height
                else:  # wall
                    from .wall_geometry import (  # noqa: PLC0415
                        compute_wall_canvas_geometry,
                    )

                    geometry = compute_wall_canvas_geometry(
                        hass, wall, list(wall.placements)
                    )
                    width, height = geometry.canvas_width, geometry.canvas_height

                rgb_png = await skill_manager.async_render_message_canvas(
                    message_text, style, width, height
                )
                filename = f"message_{message_text[:40].strip() or 'untitled'}.png"
                record = await library_manager.async_upload(
                    filename, rgb_png, albums=[_MESSAGE_ALBUM]
                )
                saved_image_id = record.get("image_id")
            except Exception as err:  # noqa: BLE001
                # The send already succeeded -- a save failure shouldn't
                # look like the whole request failed, just that nothing
                # was saved.
                _LOGGER.error("Failed to save message to library: %s", err)

        return self.json(
            {
                "success": success,
                "results": results,
                "saved_image_id": saved_image_id,
            }
        )
