"""HTTP views for integration self-update (check / install / restart / dismiss).

    GET  /api/digital_frames/update          status (installed, latest, available, banner)
    POST /api/digital_frames/update/check    force re-check against GitHub
    POST /api/digital_frames/update/install  download + install ({version?} optional)
    POST /api/digital_frames/update/restart  restart Home Assistant
    POST /api/digital_frames/update/dismiss  dismiss banner for a version ({version})
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import callback

from .update import (
    UpdateError,
    check_for_update,
    dismiss_update_banner,
    install_update,
    restart_home_assistant,
)

_LOGGER = logging.getLogger(__name__)


def _require_admin(request: web.Request) -> web.Response | None:
    user = request["hass_user"]
    if user is None or not user.is_admin:
        return web.json_response({"message": "Admin required"}, status=403)
    return None


class FraimicUpdateStatusView(HomeAssistantView):
    """GET current installed version + latest GitHub release comparison."""

    url = "/api/digital_frames/update"
    name = "api:digital_frames:update"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        try:
            status = await check_for_update(hass, force=False)
        except UpdateError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update check failed")
            return self.json_message(f"Update check failed: {err}", status_code=500)
        return self.json(status)


class FraimicUpdateCheckView(HomeAssistantView):
    """POST force a fresh GitHub check (same payload as GET)."""

    url = "/api/digital_frames/update/check"
    name = "api:digital_frames:update:check"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        denied = _require_admin(request)
        if denied is not None:
            return denied
        hass = request.app["hass"]
        try:
            status = await check_for_update(hass, force=True)
        except UpdateError as err:
            return self.json_message(str(err), status_code=502)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update check failed")
            return self.json_message(f"Update check failed: {err}", status_code=500)
        return self.json(status)


class FraimicUpdateInstallView(HomeAssistantView):
    """POST install a release (latest, or body.version)."""

    url = "/api/digital_frames/update/install"
    name = "api:digital_frames:update:install"
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

    url = "/api/digital_frames/update/restart"
    name = "api:digital_frames:update:restart"
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


class FraimicUpdateDismissView(HomeAssistantView):
    """POST dismiss the dashboard update banner for a version."""

    url = "/api/digital_frames/update/dismiss"
    name = "api:digital_frames:update:dismiss"
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
        if not version:
            # Fall back to currently advertised latest so a bare POST works.
            try:
                status = await check_for_update(hass, force=False)
                version = status.get("latest")
            except Exception:  # noqa: BLE001
                pass
        try:
            result = await dismiss_update_banner(hass, version or "")
        except UpdateError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Update banner dismiss failed")
            return self.json_message(f"Dismiss failed: {err}", status_code=500)
        return self.json(result)


@callback
def async_register_update_views(hass) -> None:
    """Register update HTTP views (called from domain setup)."""
    hass.http.register_view(FraimicUpdateStatusView())
    hass.http.register_view(FraimicUpdateCheckView())
    hass.http.register_view(FraimicUpdateInstallView())
    hass.http.register_view(FraimicUpdateRestartView())
    hass.http.register_view(FraimicUpdateDismissView())
