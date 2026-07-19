"""Fraimic Media Source integration."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_get_media_source(hass: HomeAssistant) -> FraimicMediaSource:
    """Set up the Fraimic media source."""
    return FraimicMediaSource(hass)


class FraimicMediaSource(MediaSource):
    """Provide media from Fraimic's library."""

    name = "Digital Frames"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize Fraimic media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable URL."""
        identifier = item.identifier or ""
        if identifier.startswith("image/"):
            image_id = identifier[len("image/"):]
        else:
            image_id = identifier

        manager = self.hass.data.get(DOMAIN, {}).get("_library")
        if manager is None:
            raise Unresolvable("Fraimic library not initialized")

        images = await manager.async_list_images()
        entry = next((img for img in images if img.get("image_id") == image_id), None)
        if entry is None:
            raise Unresolvable(f"Image '{image_id}' not found in Fraimic library")

        # Get local path to support local file attachments in AI/camera tasks
        from pathlib import Path  # noqa: PLC0415
        try:
            local_path = await manager.async_get_local_path(image_id)
            path_obj = Path(local_path)
        except Exception:  # noqa: BLE001
            path_obj = None

        # The URL for streaming original image
        url = f"/api/digital_frames/library/image/{image_id}"
        return PlayMedia(
            url=url,
            mime_type=entry.get("content_type", "image/png"),
            path=path_obj,
        )

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse media."""
        manager = self.hass.data.get(DOMAIN, {}).get("_library")
        if manager is None:
            raise Unresolvable("Fraimic library not initialized")

        identifier = item.identifier or ""

        if not identifier:
            # Root node: list "All Images" plus all individual albums
            albums = await manager.async_list_albums()
            children = []

            # Add folder for "All Images"
            children.append(
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier="all",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.ALBUM,
                    title="All Images",
                    can_play=False,
                    can_expand=True,
                )
            )

            for album in albums:
                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=f"album/{album['name']}",
                        media_class=MediaClass.DIRECTORY,
                        media_content_type=MediaType.ALBUM,
                        title=album["name"],
                        can_play=False,
                        can_expand=True,
                        thumbnail=(
                            f"/api/digital_frames/library/image/{album['cover_image_id']}?thumb=128"
                            if album.get("cover_image_id")
                            else None
                        ),
                    )
                )

            return BrowseMediaSource(
                domain=DOMAIN,
                identifier="",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.ALBUM,
                title="Digital Frames Library",
                can_play=False,
                can_expand=True,
                children=children,
            )

        if identifier == "all":
            images = await manager.async_list_images()
            children = []
            for img in images:
                img_id = img.get("image_id")
                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=f"image/{img_id}",
                        media_class=MediaClass.IMAGE,
                        media_content_type=img.get("content_type", "image/png"),
                        title=img.get("filename", "image"),
                        can_play=True,
                        can_expand=False,
                        thumbnail=f"/api/digital_frames/library/image/{img_id}?thumb=128",
                    )
                )
            return BrowseMediaSource(
                domain=DOMAIN,
                identifier="all",
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.ALBUM,
                title="All Images",
                can_play=False,
                can_expand=True,
                children=children,
            )

        if identifier.startswith("album/"):
            album_name = identifier[len("album/"):]
            images = await manager.async_list_images()
            children = []
            for img in images:
                if album_name in img.get("albums", []):
                    img_id = img.get("image_id")
                    children.append(
                        BrowseMediaSource(
                            domain=DOMAIN,
                            identifier=f"image/{img_id}",
                            media_class=MediaClass.IMAGE,
                            media_content_type=img.get("content_type", "image/png"),
                            title=img.get("filename", "image"),
                            can_play=True,
                            can_expand=False,
                            thumbnail=f"/api/digital_frames/library/image/{img_id}?thumb=128",
                        )
                    )
            return BrowseMediaSource(
                domain=DOMAIN,
                identifier=identifier,
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.ALBUM,
                title=album_name,
                can_play=False,
                can_expand=True,
                children=children,
            )

        if identifier.startswith("image/"):
            image_id = identifier[len("image/"):]
            images = await manager.async_list_images()
            img = next((i for i in images if i.get("image_id") == image_id), None)
            if img is None:
                raise Unresolvable(f"Image '{image_id}' not found")
            return BrowseMediaSource(
                domain=DOMAIN,
                identifier=identifier,
                media_class=MediaClass.IMAGE,
                media_content_type=img.get("content_type", "image/png"),
                title=img.get("filename", "image"),
                can_play=True,
                can_expand=False,
                thumbnail=f"/api/digital_frames/library/image/{image_id}?thumb=128",
            )

        raise Unresolvable(f"Unknown media identifier: {identifier}")
