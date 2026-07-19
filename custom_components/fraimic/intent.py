"""Custom Assist/LLM intents: generate an AI image, or send a skill (Word of
the Day, Joke of the Day, ...), to a named Fraimic frame in a single voice
command.

Registered once at domain setup (not per config entry) via
async_register_intents, so they're available to any LLM-backed conversation
agent (Google Generative AI, OpenAI, etc.) the moment Fraimic is installed --
no user-authored script or manual "expose to Assist" step required.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import intent

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

INTENT_GENERATE_AI_IMAGE = "FraimicGenerateAIImage"
INTENT_SEND_SKILL = "FraimicSendSkill"
INTENT_SHOW_IMAGE = "FraimicShowImage"


def _normalize(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _match_by_name(
    spoken_name: str,
    candidates: list[Any],
    *,
    get_name: Callable[[Any], str],
    kind: str,
) -> Any:
    """Resolve a spoken name against a list of candidates (frame devices,
    skills, ...): exact match first, falling back to a single unambiguous
    substring match (so "office" matches "Office Frame"). Raises
    HomeAssistantError -- listing every candidate's name -- on zero or
    ambiguous (>1) matches.
    """
    if not candidates:
        raise HomeAssistantError(f"No Fraimic {kind}s are configured")

    target = _normalize(spoken_name)
    named = [(candidate, _normalize(get_name(candidate) or "")) for candidate in candidates]

    exact = [candidate for candidate, name in named if name == target]
    if len(exact) == 1:
        return exact[0]

    partial = [candidate for candidate, name in named if target and target in name]
    if len(partial) == 1:
        return partial[0]

    options = ", ".join(get_name(candidate) or "?" for candidate in candidates)
    if len(partial) > 1:
        raise HomeAssistantError(
            f"'{spoken_name}' matches more than one {kind} ({options}) -- be more specific"
        )
    raise HomeAssistantError(
        f"No Fraimic {kind} matches '{spoken_name}'. Configured {kind}s: {options}"
    )


def _match_by_tag(spoken_name: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find all library images that carry a tag matching the spoken name.
    Matches exact tag first, falling back to substring match."""
    target = _normalize(spoken_name)
    if not target:
        return []

    # Exact tag match
    exact = [img for img in images if any(_normalize(t) == target for t in img.get("tags", []))]
    if exact:
        return exact

    # Substring tag match
    return [img for img in images if any(target in _normalize(t) for t in img.get("tags", []))]


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
    device = _match_by_name(
        frame_name,
        frames,
        get_name=lambda d: d.name_by_user or d.name or "",
        kind="frame",
    )
    return device.id


def _match_skill_id(hass: HomeAssistant, skill_name: str) -> str:
    """Resolve a spoken skill name (e.g. "word of the day") to a skill_id."""
    skill_manager = hass.data.get(DOMAIN, {}).get("_skills")
    skills = list(skill_manager.skills.values()) if skill_manager is not None else []
    skill = _match_by_name(skill_name, skills, get_name=lambda s: s.name, kind="skill")
    return skill.skill_id


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


class FraimicSendSkillIntent(intent.IntentHandler):
    """Send a skill (Word of the Day, Joke of the Day, ...) to a named
    frame -- works even if that skill has never been mapped to that frame
    before, since the skill is rendered fresh at send time."""

    intent_type = INTENT_SEND_SKILL
    description = (
        "Send a Fraimic skill (like Word of the Day or Joke of the Day) to "
        "a named Fraimic e-ink photo frame."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required(
                "skill", description="Name of the skill to send"
            ): intent.non_empty_string,
            vol.Required(
                "frame", description="Name of the Fraimic frame to send it to"
            ): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        skill_name: str = slots["skill"]["value"]
        frame_name: str = slots["frame"]["value"]

        response = intent_obj.create_response()

        try:
            device_id = _match_frame_device_id(hass, frame_name)
            skill_id = _match_skill_id(hass, skill_name)
        except HomeAssistantError as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err)
            )
            return response

        try:
            await hass.services.async_call(
                DOMAIN,
                "send_skill",
                {"device_id": device_id, "skill_id": skill_id},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.error("send_skill intent failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Couldn't send {skill_name}: {err}",
            )
            return response

        response.async_set_speech(f"Sure, sending {skill_name} to {frame_name} now.")
        return response


class FraimicShowImageIntent(intent.IntentHandler):
    """Show an existing image from the library on a named frame."""

    intent_type = INTENT_SHOW_IMAGE
    description = (
        "Show or display an existing image from the shared image library "
        "by its name or filename on a named Fraimic e-ink photo frame."
    )

    @property
    def slot_schema(self) -> dict:
        return {
            vol.Required(
                "image_name", description="Name or filename of the image in the library"
            ): intent.non_empty_string,
            vol.Required(
                "frame", description="Name of the Fraimic frame to send it to"
            ): intent.non_empty_string,
        }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        image_name: str = slots["image_name"]["value"]
        frame_name: str = slots["frame"]["value"]

        response = intent_obj.create_response()

        try:
            device_id = _match_frame_device_id(hass, frame_name)
        except HomeAssistantError as err:
            response.async_set_error(
                intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err)
            )
            return response

        library_manager = hass.data.get(DOMAIN, {}).get("_library")
        if library_manager is None:
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                "Library manager not initialised"
            )
            return response

        images = await library_manager.async_list_images()
        tagged_images = _match_by_tag(image_name, images)
        if tagged_images:
            import random  # noqa: PLC0415
            matched_image = random.choice(tagged_images)
        else:
            try:
                matched_image = _match_by_name(
                    image_name,
                    images,
                    get_name=lambda img: img.get("voice_name") or img["filename"],
                    kind="library image",
                )
            except HomeAssistantError as err:
                response.async_set_error(
                    intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err)
                )
                return response

        try:
            from . import _get_coordinator_by_device_id  # noqa: PLC0415
            from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

            coordinator, entry_id = _get_coordinator_by_device_id(hass, device_id)
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                raise HomeAssistantError(f"Config entry '{entry_id}' not found")

            spec = render_spec_for_hass_entry(hass, entry)
            from .panel_codec import panel_codec_for_entry  # noqa: PLC0415

            try:
                codec_id = panel_codec_for_entry(entry).id
            except ValueError:
                codec_id = None
            bin_bytes = await library_manager.async_get_bin_for_send(
                matched_image["image_id"], spec, codec_id=codec_id
            )
            await coordinator.async_send_image_or_queue(
                bin_bytes, image_id=matched_image["image_id"]
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("show_image intent failed: %s", err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Couldn't send image: {err}",
            )
            return response

        response.async_set_speech(
            f"Sure, putting {matched_image.get('voice_name') or matched_image['filename']} on {frame_name} now."
        )
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register Fraimic's custom Assist intents."""
    intent.async_register(hass, FraimicGenerateAIImageIntent())
    intent.async_register(hass, FraimicSendSkillIntent())
    intent.async_register(hass, FraimicShowImageIntent())
