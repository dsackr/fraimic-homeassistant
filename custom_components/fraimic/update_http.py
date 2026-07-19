"""HTTP views for integration self-update (check / install / restart).

    GET  /api/fraimic/update          status (installed, latest, available)
    POST /api/fraimic/update/check    force re-check against GitHub
    POST /api/fraimic/update/install  download + install ({version?} optional)
    POST /api/fraimic/update/restart  restart Home Assistant
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import callback

from .update import UpdateError, check_for_update, install_update, restart_home_assistant

_LOGGER = logging.getLogger(__name__)


def _require_admin(request: web.Request) -> web.Response | None:
    user = request["hass_user"]
    if user is None or not user.is_admin:
        return web.json_response({"message": "Admin required"}, status=403)
    return None


class FraimicUpdateStatusView(HomeAssistantView):
    """GET current installed version + latest GitHub release comparison."""

    url = "/api/fraimic/update"
    name = "api:fraimic:update"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        try:
            status = await check_for_update(hass)
        except UpdateError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update check failed")
            return self.json_message(f"Update check failed: {err}", status_code=500)
        return self.json(status)


class FraimicUpdateCheckView(HomeAssistantView):
    """POST force a fresh GitHub check (same payload as GET)."""

    url = "/api/fraimic/update/check"
    name = "api:fraimic:update:check"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        try:
            status = await check_for_update(hass)
        except UpdateError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update check failed")
            return self.json_message(f"Update check failed: {err}", status_code=500)
        return self.json(status)


class FraimicUpdateInstallView(HomeAssistantView):
    """POST install a release (latest, or body.version)."""

    url = "/api/fraimic/update/install"
    name = "api:fraimic:update:install"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        version = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                version = body.get("version")
        except Exception:  # noqa: BLE001
            pass
        try:
            result = await install_update(hass, version=version)
        except UpdateError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update install failed")
            return self.json_message(f"Install failed: {err}", status_code=500)
        return self.json(result)


class FraimicUpdateRestartView(HomeAssistantView):
    """POST restart Home Assistant after an install."""

    url = "/api/fraimic/update/restart"
    name = "api:fraimic:update:restart"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        try:
            await restart_home_assistant(hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Restart request failed")
            return self.json_message(f"Restart failed: {err}", status_code=500)
        return self.json(
            {
                "success": True,
                "message": "Home Assistant is restarting…",
            }
        )


@callback
def async_register_update_views(hass) -> None:
    """Register update HTTP views (called from domain setup)."""
    hass.http.register_view(FraimicUpdateStatusView())
    hass.http.register_view(FraimicUpdateCheckView())
    hass.http.register_view(FraimicUpdateInstallView())
    hass.http.register_view(FraimicUpdateRestartView())
