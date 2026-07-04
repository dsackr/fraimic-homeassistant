"""HTTP API views for the Fraimic shared image library.

Endpoints:
    GET  /api/fraimic/library/list                       list images + active backend
                                                            (optional ?album=<name> filter)
    POST /api/fraimic/library/upload                      upload one or more originals (multipart
                                                            "image", repeatable) into an album
                                                            (optional "album" / "new_album" fields)
    GET  /api/fraimic/library/image/{id}                  stream an original (for thumbnails)
    POST /api/fraimic/library/image/{id}/albums           replace an image's album tags
    POST /api/fraimic/library/send                        send a library image to a frame
    POST /api/fraimic/library/crop                         save a manual crop rect for one image+resolution
    DELETE /api/fraimic/library/crop                       clear a saved crop, revert to auto framing
    GET  /api/fraimic/library/albums                      list albums with photo counts + cover image
    POST /api/fraimic/library/albums                      rename an album
    DELETE /api/fraimic/library/albums                     delete an album (untags, doesn't delete photos)
    POST /api/fraimic/library/albums/{name}/images         add a batch of images to an album (creates it
                                                            if the name isn't in use yet)
    GET  /api/fraimic/frames                              list frames with their configured width/height
    GET  /api/fraimic/library/settings                    current backend name
    POST /api/fraimic/library/settings                    change backend (validates first;
                                                            used directly by Local + Dropbox)
    POST /api/fraimic/library/discover                    adopt files added outside Fraimic
                                                            (Dropbox only -- see LibraryBackend.
                                                            supports_discovery)
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

from .const import (
    CONF_HEIGHT,
    CONF_HOST,
    CONF_ORIENTATION,
    CONF_SIZE,
    CONF_WIDTH,
    DOMAIN,
    ORIENTATION_AUTO,
)
from .frame_types import FRAME_TYPES
from .helpers import render_spec_for_entry
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
        album = request.query.get("album")
        if album:
            images = [img for img in images if album in (img.get("albums") or [])]
        return self.json({"images": images, "backend": manager.backend_name})


class FraimicLibraryUploadView(HomeAssistantView):
    """Upload one or more original images into the library, into a single
    target album (new or existing; defaults to the "Images" album).

    Returns as soon as each original is stored -- .bin generation for every
    resolution currently in use across configured frames happens in the
    background (see LibraryManager.async_upload / _schedule_backfill).
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

        image_fields = data.getall("image", [])
        if not image_fields:
            return self.json_message("image file is required", status_code=400)

        from .library import DEFAULT_ALBUM  # noqa: PLC0415

        new_album = (data.get("new_album") or "").strip()
        existing_album = (data.get("album") or "").strip()
        target_album = new_album or existing_album
        albums = [DEFAULT_ALBUM] if not target_album or target_album == DEFAULT_ALBUM else [DEFAULT_ALBUM, target_album]

        # Each file is uploaded independently -- one bad file in a multi-file
        # batch shouldn't strand the others (or the ones already persisted
        # earlier in this same loop) in limbo with no way for the caller to
        # know they actually succeeded.
        records = []
        errors = []
        for image_field in image_fields:
            filename = getattr(image_field, "filename", None) or "image"
            try:
                # image_field.file is a spooled temp file -- .read() is
                # blocking I/O and must not run directly on the event loop.
                raw_bytes: bytes = await hass.async_add_executor_job(
                    image_field.file.read  # type: ignore[union-attr]
                )
                if not raw_bytes:
                    raise ValueError("uploaded file is empty")
                records.append(await manager.async_upload(filename, raw_bytes, albums))
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Library upload failed for '%s': %s", filename, err)
                errors.append({"filename": filename, "message": str(err)})

        return self.json({"success": bool(records), "images": records, "errors": errors})


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


class FraimicLibraryImageAlbumsView(HomeAssistantView):
    """Replace the full set of album tags on one library image."""

    url = "/api/fraimic/library/image/{image_id}/albums"
    name = "api:fraimic:library:image:albums"
    requires_auth = True

    async def post(self, request: web.Request, image_id: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        albums = (body or {}).get("albums")
        if not isinstance(albums, list) or not all(isinstance(a, str) for a in albums):
            return self.json_message("albums must be a list of strings", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            record = await manager.async_set_image_albums(image_id, albums)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to set albums for %s: %s", image_id, err)
            return self.json_message(f"Failed to set albums: {err}", status_code=500)

        return self.json({"success": True, "image": record})


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

        spec = render_spec_for_entry(entry)

        try:
            bin_bytes = await manager.async_get_bin_for_send(image_id, spec)
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


class FraimicLibraryCropView(HomeAssistantView):
    """Save (POST) or clear (DELETE) a manual crop rectangle for one
    library image at one resolution.

    Saving (or clearing) invalidates that resolution's cached .bin so the
    next send re-converts with the new crop (or reverts to the automatic
    centered cover-crop render).
    """

    url = "/api/fraimic/library/crop"
    name = "api:fraimic:library:crop"
    requires_auth = True

    @staticmethod
    def _parse_common(body: dict) -> "tuple[str, int, int] | None":
        image_id = (body or {}).get("image_id")
        width = (body or {}).get("width")
        height = (body or {}).get("height")
        if not image_id or not isinstance(width, int) or not isinstance(height, int):
            return None
        return image_id, width, height

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        parsed = self._parse_common(body)
        if parsed is None:
            return self.json_message(
                "image_id, width, and height are required", status_code=400
            )
        image_id, width, height = parsed

        crop_box = (body or {}).get("crop_box")
        if (
            not isinstance(crop_box, list)
            or len(crop_box) != 4
            or not all(isinstance(v, (int, float)) for v in crop_box)
        ):
            return self.json_message(
                "crop_box must be [x0, y0, x1, y1]", status_code=400
            )

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            record = await manager.async_set_crop(image_id, width, height, crop_box)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to save crop for %s: %s", image_id, err)
            return self.json_message(f"Failed to save crop: {err}", status_code=500)

        return self.json({"success": True, "image": record})

    async def delete(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        parsed = self._parse_common(body)
        if parsed is None:
            return self.json_message(
                "image_id, width, and height are required", status_code=400
            )
        image_id, width, height = parsed

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            record = await manager.async_clear_crop(image_id, width, height)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=404)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to clear crop for %s: %s", image_id, err)
            return self.json_message(f"Failed to clear crop: {err}", status_code=500)

        return self.json({"success": True, "image": record})


class FraimicLibraryAlbumsView(HomeAssistantView):
    """List, rename, or delete albums.

    Renaming/deleting an album never touches the underlying photos -- it
    only rewrites which album tags they carry.
    """

    url = "/api/fraimic/library/albums"
    name = "api:fraimic:library:albums"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        albums = await manager.async_list_albums()
        return self.json({"albums": albums})

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        old_name = (body or {}).get("old_name")
        new_name = (body or {}).get("new_name")
        if not old_name or not new_name:
            return self.json_message("old_name and new_name are required", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            count = await manager.async_rename_album(old_name, new_name)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to rename album '%s': %s", old_name, err)
            return self.json_message(f"Failed to rename album: {err}", status_code=500)

        return self.json({"success": True, "count": count})

    async def delete(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        name = (body or {}).get("name")
        if not name:
            return self.json_message("name is required", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            count = await manager.async_delete_album(name)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to delete album '%s': %s", name, err)
            return self.json_message(f"Failed to delete album: {err}", status_code=500)

        return self.json({"success": True, "count": count})


class FraimicLibraryAlbumImagesView(HomeAssistantView):
    """Add a batch of existing images to an album in one call. Doubles as
    "create an album" -- a fresh (not-yet-used) name is all that takes."""

    url = "/api/fraimic/library/albums/{name}/images"
    name = "api:fraimic:library:albums:images"
    requires_auth = True

    async def post(self, request: web.Request, name: str) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        try:
            body = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON body: {err}", status_code=400)

        image_ids = body.get("image_ids") if isinstance(body, dict) else None
        if not isinstance(image_ids, list) or not all(isinstance(i, str) for i in image_ids):
            return self.json_message("image_ids must be a list of strings", status_code=400)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            count = await manager.async_add_images_to_album(image_ids, name)
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to add images to album '%s': %s", name, err)
            return self.json_message(f"Failed to add images to album: {err}", status_code=500)

        return self.json({"success": True, "count": count})


class FraimicFramesView(HomeAssistantView):
    """List every configured Fraimic frame's entry_id plus its fixed
    width/height, physical size label, origin (official/clone), and host.
    entry.data isn't exposed via the generic config_entries/get WS command
    the panel otherwise uses for discovery, so the crop editor and sidebar
    panel call this directly for data that only lives in entry.data."""

    url = "/api/fraimic/frames"
    name = "api:fraimic:frames"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        frames = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            width = entry.data.get(CONF_WIDTH)
            height = entry.data.get(CONF_HEIGHT)
            if isinstance(width, int) and isinstance(height, int):
                frame_type = FRAME_TYPES.get(entry.data.get(CONF_SIZE))
                spec = render_spec_for_entry(entry)
                frames.append(
                    {
                        "entry_id": entry.entry_id,
                        "title": entry.title,
                        # Effective composition dimensions -- what the crop
                        # editor's aspect ratio must match and what crop
                        # rects are keyed by. Reflects the orientation lock.
                        "width": spec.width,
                        "height": spec.height,
                        # Native (frame-reported) panel dimensions.
                        "native_width": width,
                        "native_height": height,
                        "orientation": entry.options.get(
                            CONF_ORIENTATION, ORIENTATION_AUTO
                        ),
                        "size": entry.data.get(CONF_SIZE),
                        "host": entry.data.get(CONF_HOST),
                        "origin": frame_type.origin if frame_type else None,
                        "platform": frame_type.platform if frame_type else None,
                    }
                )
        return self.json({"frames": frames})


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


class FraimicLibraryDiscoverView(HomeAssistantView):
    """Adopt files added to the active backend outside of Fraimic (only
    supported by the Dropbox backend today -- see
    LibraryBackend.supports_discovery)."""

    url = "/api/fraimic/library/discover"
    name = "api:fraimic:library:discover"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)

        from .library import LibraryBackendError  # noqa: PLC0415

        try:
            result = await manager.async_discover()
        except LibraryBackendError as err:
            return self.json_message(str(err), status_code=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Library discovery failed: %s", err)
            return self.json_message(f"Discovery failed: {err}", status_code=500)

        return self.json(result)


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


class FraimicFrameReloadView(HomeAssistantView):
    """Reload the config entry for a specific frame."""

    url = "/api/fraimic/frame/reload"
    name = "api:fraimic:frame:reload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        try:
            data = await request.json()
        except Exception as err:  # noqa: BLE001
            return self.json_message(f"Invalid JSON: {err}", status_code=400)

        entry_id = data.get("entry_id")
        if not entry_id:
            return self.json_message("entry_id is required", status_code=400)

        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return self.json_message("Frame entry not found", status_code=404)

        result = await hass.config_entries.async_reload(entry_id)
        return self.json({"success": result})
