"""HTTP API views for the Fraimic shared image library.

Endpoints:
    GET  /api/fraimic/library/list                       list images + active backend
    POST /api/fraimic/library/upload                      upload a new original (multipart "image")
    GET  /api/fraimic/library/image/{id}                  stream an original (for thumbnails)
    POST /api/fraimic/library/send                        send a library image to a frame
    GET  /api/fraimic/library/settings                    current backend name
    POST /api/fraimic/library/settings                    change backend (validates first;
                                                            used directly by Local + Dropbox)
    GET  /api/fraimic/library/oauth/google/redirect_uri   the URI to register in Google Cloud Console
    POST /api/fraimic/library/oauth/google/start          begin the Google consent flow
    GET  /api/fraimic/library/oauth/google/callback       Google's redirect target (no auth --
                                                            this is a plain browser navigation)
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_HEIGHT, CONF_WIDTH, DOMAIN
from .http_api import resolve_frame_by_entity

_LOGGER = logging.getLogger(__name__)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def _get_manager(hass):
    domain_data = hass.data.get(DOMAIN, {})
    manager = domain_data.get("_library")
    if manager is None:
        raise RuntimeError("Library manager not initialised")
    return manager


class FraimicLibraryListView(HomeAssistantView):
    """List every image currently in the library."""

    url = "/api/fraimic/library/list"
    name = "api:fraimic:library:list"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        images = await manager.async_list_images()
        return self.json({"images": images, "backend": manager.backend_name})


class FraimicLibraryUploadView(HomeAssistantView):
    """Upload a new original image into the library.

    Eagerly converts it to a .bin for every resolution currently in use
    across configured frames (see LibraryManager.async_upload).
    """

    url = "/api/fraimic/library/upload"
    name = "api:fraimic:library:upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            data = await request.post()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid request body: {err}", status_code=400)

        image_field = data.get("image")
        if image_field is None:
            return self.json_message("image file is required", status_code=400)

        try:
            raw_bytes: bytes = image_field.file.read()  # type: ignore[union-attr]
            filename = getattr(image_field, "filename", None) or "image"
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Could not read image data: {err}", status_code=400)

        if not raw_bytes:
            return self.json_message("Uploaded file is empty", status_code=400)

        try:
            record = await manager.async_upload(filename, raw_bytes)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Library upload failed: %s", err)
            return self.json_message(f"Upload failed: {err}", status_code=500)

        return self.json({"success": True, "image": record})


class FraimicLibraryImageView(HomeAssistantView):
    """Stream a stored original (GET, for thumbnails) or remove it (DELETE)."""

    url = "/api/fraimic/library/image/{image_id}"
    name = "api:fraimic:library:image"
    requires_auth = True

    async def get(self, request: web.Request, image_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        try:
            raw_bytes, content_type = await manager.async_get_original(image_id)
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Image not found: {err}", status_code=404)
        return web.Response(body=raw_bytes, content_type=content_type)

    async def delete(self, request: web.Request, image_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        try:
            await manager.async_delete(image_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete library image %s: %s", image_id, err)
            return self.json_message(f"Delete failed: {err}", status_code=500)
        return self.json({"success": True})


class FraimicLibrarySendView(HomeAssistantView):
    """Send an existing library image to a frame.

    Reuses a cached .bin for that frame's resolution if one exists; otherwise
    converts on the fly and caches the result for next time.
    """

    url = "/api/fraimic/library/send"
    name = "api:fraimic:library:send"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.post()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid request body: {err}", status_code=400)

        entity_id = body.get("entity_id")
        image_id = body.get("image_id")

        if not entity_id:
            return self.json_message("entity_id is required", status_code=400)
        if not image_id:
            return self.json_message("image_id is required", status_code=400)

        try:
            coordinator, entry = resolve_frame_by_entity(hass, entity_id)
        except ValueError as err:
            return self.json_message(str(err), status_code=404)

        width: int = entry.data[CONF_WIDTH]
        height: int = entry.data[CONF_HEIGHT]

        try:
            bin_bytes = await manager.async_get_bin_for_send(image_id, width, height)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Library send conversion failed: %s", err)
            return self.json_message(f"Conversion failed: {err}", status_code=500)

        try:
            await coordinator.async_send_image(bin_bytes)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to send library image to frame %s: %s", coordinator.host, err
            )
            return self.json_message(f"Failed to send to frame: {err}", status_code=502)

        return self.json({"success": True, "bytes_sent": len(bin_bytes)})


class FraimicLibrarySettingsView(HomeAssistantView):
    """Get/set which storage backend the library uses."""

    url = "/api/fraimic/library/settings"
    name = "api:fraimic:library:settings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        return self.json({"backend": manager.backend_name})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            settings = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        if not isinstance(settings, dict) or "backend" not in settings:
            return self.json_message("'backend' field is required", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            await manager.async_set_backend(settings)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to set library backend: %s", err)
            return self.json_message(f"Failed to set backend: {err}", status_code=500)

        return self.json({"success": True, "backend": manager.backend_name})


class FraimicLibraryGoogleRedirectUriView(HomeAssistantView):
    """Tell the panel which redirect URI to register in Google Cloud Console."""

    url = "/api/fraimic/library/oauth/google/redirect_uri"
    name = "api:fraimic:library:oauth:google:redirect_uri"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        return self.json({"redirect_uri": manager.google_redirect_uri()})


class FraimicLibraryGoogleOAuthStartView(HomeAssistantView):
    """Begin the Google consent flow: stash the client id/secret the user
    just entered, return the URL to open so they can sign in."""

    url = "/api/fraimic/library/oauth/google/start"
    name = "api:fraimic:library:oauth:google:start"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        client_id = (body or {}).get("client_id", "").strip()
        client_secret = (body or {}).get("client_secret", "").strip()
        if not client_id or not client_secret:
            return self.json_message("client_id and client_secret are required", status_code=400)

        redirect_uri = manager.google_redirect_uri()
        if redirect_uri is None:
            return self.json_message(
                "Set an External URL under Settings > System > Network in "
                "Home Assistant first -- Google needs a stable redirect URL.",
                status_code=400,
            )

        state = manager.create_pending_google_oauth(client_id, client_secret)
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _GOOGLE_DRIVE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"
        return self.json({"auth_url": auth_url, "redirect_uri": redirect_uri})


class FraimicLibraryGoogleOAuthCallbackView(HomeAssistantView):
    """Google redirects the user's browser here after they grant (or deny)
    consent. This is a plain top-level navigation -- no Authorization header
    -- so it must stay unauthenticated. It's protected instead by the
    one-time `state` token minted in the start step above."""

    url = "/api/fraimic/library/oauth/google/callback"
    name = "api:fraimic:library:oauth:google:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        error = request.query.get("error")
        if error:
            return self._page(f"Google declined: {error}", ok=False)

        code = request.query.get("code")
        state = request.query.get("state")
        if not code or not state:
            return self._page("Missing code or state in Google's response.", ok=False)

        pending = manager.pop_pending_google_oauth(state)
        if pending is None:
            return self._page(
                "This authorization link expired or was already used. Go back to "
                "Home Assistant and click 'Connect Google Drive' again.",
                ok=False,
            )

        redirect_uri = manager.google_redirect_uri()
        session = async_get_clientsession(hass)
        try:
            resp = await session.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "client_id": pending["client_id"],
                    "client_secret": pending["client_secret"],
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as err:  # noqa: BLE001
            return self._page(f"Couldn't reach Google: {err}", ok=False)

        if resp.status >= 400:
            text = await resp.text()
            return self._page(f"Google token exchange failed: {text[:300]}", ok=False)

        token_data = await resp.json()
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return self._page(
                "Google didn't return a refresh token. This usually means this "
                "Google account already authorized this app before -- remove "
                "Fraimic's access at myaccount.google.com/permissions and try again.",
                ok=False,
            )

        settings = {
            "backend": "google_drive",
            "client_id": pending["client_id"],
            "client_secret": pending["client_secret"],
            "refresh_token": refresh_token,
        }

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            await manager.async_set_backend(settings)
        except LibraryBackendError as err:
            return self._page(f"Connected to Google, but setup failed: {err}", ok=False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Google Drive setup failed after OAuth: %s", err)
            return self._page(f"Connected to Google, but setup failed: {err}", ok=False)

        return self._page(
            "Google Drive connected! You can close this tab and go back to Home Assistant.",
            ok=True,
        )

    @staticmethod
    def _page(message: str, ok: bool) -> web.Response:
        color = "#15803d" if ok else "#b91c1c"
        html = (
            "<!DOCTYPE html><html><body style=\"font-family:sans-serif;"
            "text-align:center;padding:60px 20px\">"
            f"<h2 style=\"color:{color}\">{message}</h2>"
            "</body></html>"
        )
        return web.Response(text=html, content_type="text/html", status=200 if ok else 400)
