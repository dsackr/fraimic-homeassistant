"""Custom Assist/LLM intent: generate an AI image and send it to a named
Fraimic frame in a single voice command.

Registered once at domain setup (not per config entry) via
async_register_intents, so it's available to any LLM-backed conversation
agent (Google Generative AI, OpenAI, etc.) the moment Fraimic is installed --
no user-authored script or manual "expose to Assist" step required.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import intent

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

INTENT_GENERATE_AI_IMAGE = "FraimicGenerateAIImage"


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _match_frame_device_id(hass: HomeAssistant, frame_name: str) -> str:
    """Resolve a spoken frame name to a Fraimic device_id.

    Matches against the same device names shown in the "Frame" selector on
    fraimic.generate_ai_image -- exact match first, falling back to a single
    unambiguous substring match (so "office" matches "Office Frame").
    """
    dev_reg = dr.async_get(hass)
    frames = [
        device
        for device in dev_reg.devices.values()
        if any(identifier[0] == DOMAIN for identifier in device.identifiers)
    ]
    if not frames:
        raise HomeAssistantError("No Fraimic frames are configured")

    target = _normalize(frame_name)
    named = [(device, _normalize(device.name_by_user or device.name or "")) for device in frames]

    exact = [device for device, name in named if name == target]
    if len(exact) == 1:
        return exact[0].id

    partial = [device for device, name in named if target and target in name]
    if len(partial) == 1:
        return partial[0].id

    options = ", ".join(device.name_by_user or device.name or "?" for device in frames)
    if len(partial) > 1:
        raise HomeAssistantError(
            f"'{frame_name}' matches more than one frame ({options}) -- be more specific"
        )
    raise HomeAssistantError(
        f"No Fraimic frame matches '{frame_name}'. Configured frames: {options}"
    )


class FraimicGenerateAIImageIntent(intent.IntentHandler):
    """Generate an image from a text prompt and send it to a named frame."""

    intent_type = INTENT_GENERATE_AI_IMAGE
    description = (
        "Generate an image from a text description and send it to a named "
        "Fraimic e-ink photo frame."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required(
                "prompt", description="What image to generate"
            ): intent.non_empty_string,
            vol.Required(
                "frame", description="Name of the Fraimic frame to send it to"
            ): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        prompt: str = slots["prompt"]["value"]
        frame_name: str = slots["frame"]["value"]

        response = intent_obj.create_response()

        try:
            device_id = _match_frame_device_id(hass, frame_name)
        except HomeAssistantError as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err)
            )
            return response

        try:
            await hass.services.async_call(
                DOMAIN,
                "generate_ai_image",
                {"device_id": device_id, "prompt": prompt},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.error("generate_ai_image intent failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Couldn't generate that image: {err}",
            )
            return response

        response.async_set_speech(f"Sure, sending that to {frame_name} now.")
        return response


def async_register_intents(hass: HomeAssistant) -> None:
    """Register Fraimic's custom Assist intents."""
    intent.async_register(hass, FraimicGenerateAIImageIntent())
