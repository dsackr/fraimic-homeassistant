"""HTTP API views for Fraimic scheduled events.

Endpoints:
    GET    /api/digital_frames/schedules                 list schedules (+ computed next_fire_at)
    POST   /api/digital_frames/schedules                 create ({name, action, trigger[, enabled]})
    POST   /api/digital_frames/schedules/{schedule_id}   update (any of name/action/trigger/enabled)
    DELETE /api/digital_frames/schedules/{schedule_id}   delete + disarm
"""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_schedule_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_schedules")
    if manager is None:
        raise RuntimeError("Schedule manager not initialised")
    return manager


class FraimicSchedulesView(HomeAssistantView):
    """List (GET) or create (POST) schedules."""

    url = "/api/digital_frames/schedules"
    name = "api:digital_frames:schedules"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_schedule_manager(hass)
        schedules = []
        for record in await manager.async_list_schedules():
            # next_fire_at is computed server-side so the panel never has to
            # re-implement recurrence math (weekday sets, month-length
            # clamping) to show "fires next at ...".
            schedule = await manager.async_get_schedule(record["schedule_id"])
            record["next_fire_at"] = (
                manager.next_fire_at(schedule) if schedule is not None else None
            )
            schedules.append(record)
        return self.json({"schedules": schedules})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_schedule_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        from .schedules import ScheduleError  # noqa: PLC0415

        try:
            schedule = await manager.async_create_schedule(
                body.get("name"),
                body.get("action"),
                body.get("trigger"),
                enabled=body.get("enabled", True),
            )
        except ScheduleError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to create schedule: %s", err)
            return self.json_message(
                f"Failed to create schedule: {err}", status_code=500
            )

        return self.json({"success": True, "schedule": schedule})


class FraimicScheduleView(HomeAssistantView):
    """Update (POST) or delete (DELETE) a single schedule."""

    url = "/api/digital_frames/schedules/{schedule_id}"
    name = "api:digital_frames:schedules:one"
    requires_auth = True

    async def post(self, request: web.Request, schedule_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_schedule_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)
        if not isinstance(body, dict):
            return self.json_message("Request body must be an object", status_code=400)

        from .schedules import ScheduleError  # noqa: PLC0415

        changes = {
            key: body[key]
            for key in ("name", "action", "trigger", "enabled")
            if key in body
        }
        try:
            schedule = await manager.async_update_schedule(schedule_id, changes)
        except ScheduleError as err:
            status = 404 if "not found" in str(err) else 400
            return self.json_message(str(err), status_code=status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to update schedule '%s': %s", schedule_id, err)
            return self.json_message(
                f"Failed to update schedule: {err}", status_code=500
            )

        return self.json({"success": True, "schedule": schedule})

    async def delete(self, request: web.Request, schedule_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_schedule_manager(hass)
        try:
            await manager.async_delete_schedule(schedule_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete schedule '%s': %s", schedule_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})
