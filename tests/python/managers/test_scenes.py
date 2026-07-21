"""Scenes: named multi-frame image assignments, CRUD + send (KPF 16).

If this silently breaks: partial-failure semantics could be wrong (one
dead frame blocking the whole scene, or a fully-failed scene reporting
success); duplicate-name collisions not caught.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.scenes import SceneError, SceneManager


@pytest.fixture
def scene_manager(hass):
    return SceneManager(hass)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_scene(scene_manager):
    result = await scene_manager.async_save_scene("Movie Night", {"entry-1": "img-1"})
    assert result["name"] == "Movie Night"
    assert result["mappings"] == {"entry-1": "img-1"}
    assert result["source"] == "user"


async def test_update_existing_scene(scene_manager):
    created = await scene_manager.async_save_scene("Original", {"entry-1": "img-1"})
    updated = await scene_manager.async_save_scene(
        "Renamed", {"entry-1": "img-2"}, scene_id=created["scene_id"]
    )
    assert updated["scene_id"] == created["scene_id"]
    assert updated["name"] == "Renamed"
    assert updated["mappings"] == {"entry-1": "img-2"}
    assert len(await scene_manager.async_list_scenes()) == 1


async def test_delete_scene(scene_manager):
    created = await scene_manager.async_save_scene("Gone Soon", {"entry-1": "img-1"})
    await scene_manager.async_delete_scene(created["scene_id"])
    assert await scene_manager.async_get_scene(created["scene_id"]) is None


async def test_duplicate_name_rejected(scene_manager):
    await scene_manager.async_save_scene("Movie Night", {"entry-1": "img-1"})
    with pytest.raises(SceneError, match="already exists"):
        await scene_manager.async_save_scene("Movie Night", {"entry-2": "img-2"})


async def test_renaming_scene_to_its_own_name_allowed(scene_manager):
    created = await scene_manager.async_save_scene("Movie Night", {"entry-1": "img-1"})
    # Saving with the same name and same scene_id must not collide with itself.
    result = await scene_manager.async_save_scene(
        "Movie Night", {"entry-1": "img-2"}, scene_id=created["scene_id"]
    )
    assert result["mappings"] == {"entry-1": "img-2"}


async def test_empty_mappings_rejected(scene_manager):
    with pytest.raises(SceneError, match="at least one frame"):
        await scene_manager.async_save_scene("Empty", {})


async def test_empty_name_rejected(scene_manager):
    with pytest.raises(SceneError, match="can't be empty"):
        await scene_manager.async_save_scene("   ", {"entry-1": "img-1"})


async def test_update_of_deleted_scene_fails_cleanly(scene_manager):
    created = await scene_manager.async_save_scene("Temp", {"entry-1": "img-1"})
    await scene_manager.async_delete_scene(created["scene_id"])

    with pytest.raises(SceneError, match="not found"):
        await scene_manager.async_save_scene(
            "Temp Renamed", {"entry-1": "img-2"}, scene_id=created["scene_id"]
        )


async def test_deleting_scene_disarms_referencing_schedules(hass, scene_manager):
    created = await scene_manager.async_save_scene("Referenced", {"entry-1": "img-1"})

    calls = []

    class _FakeScheduleManager:
        async def async_handle_scene_deleted(self, scene_id):
            calls.append(scene_id)

    hass.data.setdefault(DOMAIN, {})["_schedules"] = _FakeScheduleManager()

    await scene_manager.async_delete_scene(created["scene_id"])

    assert calls == [created["scene_id"]]


# ---------------------------------------------------------------------------
# async_send_mappings: fan-out + partial-failure semantics
# ---------------------------------------------------------------------------


class _FakeLibrary:
    """Returns fixed bin bytes for known image_ids, raises for unknown ones
    (simulating a deleted/missing image) -- avoids pulling in the real
    LibraryManager just to test the fan-out/aggregation logic here."""

    def __init__(self):
        self.crop_box_override_calls = []

    async def async_get_bin_for_send(
        self, image_id, spec, pack_method=None, codec_id=None, crop_box_override=None
    ):
        if image_id == "missing-image":
            raise FileNotFoundError(f"no such image: {image_id}")
        if crop_box_override is not None:
            self.crop_box_override_calls.append((image_id, tuple(crop_box_override)))
            return f"bin-for-{image_id}-crop-{tuple(crop_box_override)}".encode()
        return f"bin-for-{image_id}".encode()


@pytest.fixture
def library_and_coordinators(hass, make_coordinator, make_frame_entry):
    hass.data.setdefault(DOMAIN, {})["_library"] = _FakeLibrary()

    def _setup(*, count=1, host_prefix="192.168.1."):
        entries = []
        for i in range(count):
            entry = make_frame_entry(host=f"{host_prefix}{50+i}", entry_id=f"entry-{i}")
            coordinator = make_coordinator(entry)
            hass.data[DOMAIN][entry.entry_id] = coordinator
            entries.append(entry)
        return entries

    return _setup


async def test_send_mappings_all_succeed(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {e.entry_id: f"img-{i}" for i, e in enumerate(entries)}
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert len(result["results"]) == 2
    assert all(r["success"] for r in result["results"])


async def test_send_mappings_partial_failure_does_not_block_others(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {entries[0].entry_id: "missing-image", entries[1].entry_id: "img-ok"}
    result = await scene_manager.async_send_mappings(hass, mappings)

    results_by_entry = {r["entry_id"]: r for r in result["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is False
    assert results_by_entry[entries[1].entry_id]["success"] is True


async def test_send_mappings_removed_frame_reports_failure_not_crash(
    hass, scene_manager, library_and_coordinators
):
    result = await scene_manager.async_send_mappings(hass, {"never-configured": "img-1"})
    assert result["results"] == [
        {
            "entry_id": "never-configured",
            "success": False,
            "message": "Frame is no longer configured",
        }
    ]


async def test_send_mappings_queued_reported_not_as_failure_shape(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=1)

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": False, "queued": True}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    result = await scene_manager.async_send_mappings(hass, {entries[0].entry_id: "img-1"})
    assert result["results"] == [{"entry_id": entries[0].entry_id, "success": False, "queued": True}]


async def test_send_scene_not_found_raises(hass, scene_manager):
    with pytest.raises(SceneError, match="not found"):
        await scene_manager.async_send_scene(hass, "nonexistent-scene-id")


# ---------------------------------------------------------------------------
# Skill mappings: `{"type": "skill", "skill_id": ...}` instead of a bare
# library image_id -- generated fresh at send time, see skills.py.
# ---------------------------------------------------------------------------


async def test_save_scene_accepts_skill_mapping(scene_manager):
    result = await scene_manager.async_save_scene(
        "Daily Content", {"entry-1": {"type": "skill", "skill_id": "word_of_the_day"}}
    )
    assert result["mappings"] == {"entry-1": {"type": "skill", "skill_id": "word_of_the_day"}}


async def test_save_scene_rejects_malformed_mapping_value(scene_manager):
    with pytest.raises(SceneError, match="Invalid mapping"):
        await scene_manager.async_save_scene("Bad", {"entry-1": {"type": "skill"}})
    with pytest.raises(SceneError, match="Invalid mapping"):
        await scene_manager.async_save_scene("Bad", {"entry-1": {"foo": "bar"}})


class _FakeSkillManager:
    def __init__(self):
        self.rendered_for = []
        self.rendered_messages = []
        self.rendered_wall_crops = []

    async def async_render_for_entry(self, skill_id, entry):
        self.rendered_for.append((skill_id, entry.entry_id))
        if skill_id == "broken-skill":
            raise Exception("render blew up")
        if skill_id == "image-skill":
            return {"kind": "image_id", "image_id": "resolved-image"}
        return {
            "kind": "bin",
            "bytes": f"bin-for-{skill_id}".encode(),
            "preview": f"preview-for-{skill_id}".encode(),
        }

    async def async_render_message_for_entry(self, message_text, style, entry):
        self.rendered_messages.append((message_text, style, entry.entry_id))
        if message_text == "boom":
            raise Exception("message render blew up")
        return {
            "kind": "bin",
            "bytes": f"bin-for-{message_text}-{style}".encode(),
            "preview": f"preview-for-{message_text}".encode(),
        }

    async def async_render_message_wall_crop_for_entry(
        self, message_text, style, wall_id, entry
    ):
        self.rendered_wall_crops.append((message_text, style, wall_id, entry.entry_id))
        if wall_id == "broken-wall":
            raise Exception("wall render blew up")
        return {
            "kind": "bin",
            "bytes": f"bin-for-{wall_id}-{entry.entry_id}".encode(),
            "preview": f"preview-for-{wall_id}".encode(),
        }


async def test_send_mappings_skill_bin_kind_sent_without_image_id(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    sent_calls = []

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        sent_calls.append((image_bytes, image_id, thumbnail))
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {entries[0].entry_id: {"type": "skill", "skill_id": "word_of_the_day"}}
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"] == [{"entry_id": entries[0].entry_id, "success": True}]
    # The renderer's preview must ride along as the thumbnail so the frame's
    # last-image state survives a text-skill send (it has no image_id).
    assert sent_calls == [
        (b"bin-for-word_of_the_day", None, b"preview-for-word_of_the_day")
    ]


async def test_send_mappings_skill_image_kind_routes_through_library(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {entries[0].entry_id: {"type": "skill", "skill_id": "image-skill"}}
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"] == [{"entry_id": entries[0].entry_id, "success": True}]


async def test_send_mappings_skill_render_failure_does_not_block_other_mappings(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {"type": "skill", "skill_id": "broken-skill"},
        entries[1].entry_id: "img-ok",
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    results_by_entry = {r["entry_id"]: r for r in result["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is False
    assert "render blew up" in results_by_entry[entries[0].entry_id]["message"]
    assert results_by_entry[entries[1].entry_id]["success"] is True


async def test_send_mappings_skill_without_skill_manager_fails_that_mapping_only(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)
    # No "_skills" manager registered at all.

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {"type": "skill", "skill_id": "word_of_the_day"},
        entries[1].entry_id: "img-ok",
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    results_by_entry = {r["entry_id"]: r for r in result["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is False
    assert "Skill manager not initialised" in results_by_entry[entries[0].entry_id]["message"]
    assert results_by_entry[entries[1].entry_id]["success"] is True


# ---------------------------------------------------------------------------
# Message mappings: ephemeral "message"/"message_wall_crop" (never
# persisted, see skills.py) and the persistable "image_crop" (a saved
# message's library image with a per-mapping crop, sidestepping
# library.py's per-resolution manual-crop collision -- see
# library.async_get_bin_for_send's crop_box_override).
# ---------------------------------------------------------------------------


async def test_send_mappings_message_bin_kind_sent_without_image_id(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {
            "type": "message",
            "message_text": "Happy Birthday!",
            "style": "plain",
        }
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"] == [{"entry_id": entries[0].entry_id, "success": True}]


async def test_send_mappings_message_render_failure_isolated(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {"type": "message", "message_text": "boom", "style": "plain"},
        entries[1].entry_id: "img-ok",
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    results_by_entry = {r["entry_id"]: r for r in result["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is False
    assert "message render blew up" in results_by_entry[entries[0].entry_id]["message"]
    assert results_by_entry[entries[1].entry_id]["success"] is True


async def test_send_mappings_message_missing_text_rejected(
    hass, scene_manager, library_and_coordinators
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    mappings = {entries[0].entry_id: {"type": "message", "style": "plain"}}
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"][0]["success"] is False
    assert "Invalid mapping" in result["results"][0]["message"]


async def test_send_mappings_message_wall_crop_bin_kind(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {
            "type": "message_wall_crop",
            "message_text": "Happy Birthday!",
            "style": "plain",
            "wall_id": "wall-1",
        }
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"] == [{"entry_id": entries[0].entry_id, "success": True}]


async def test_send_mappings_message_wall_crop_render_failure_isolated(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    entries = library_and_coordinators(count=2)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {
            "type": "message_wall_crop",
            "message_text": "Hi",
            "style": "plain",
            "wall_id": "broken-wall",
        },
        entries[1].entry_id: "img-ok",
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    results_by_entry = {r["entry_id"]: r for r in result["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is False
    assert "wall render blew up" in results_by_entry[entries[0].entry_id]["message"]
    assert results_by_entry[entries[1].entry_id]["success"] is True


async def test_send_mappings_message_wall_crop_missing_wall_id_rejected(
    hass, scene_manager, library_and_coordinators
):
    entries = library_and_coordinators(count=1)
    hass.data[DOMAIN]["_skills"] = _FakeSkillManager()

    mappings = {
        entries[0].entry_id: {
            "type": "message_wall_crop",
            "message_text": "Hi",
            "style": "plain",
        }
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"][0]["success"] is False
    assert "Invalid mapping" in result["results"][0]["message"]


async def test_save_scene_accepts_image_crop_mapping(scene_manager):
    result = await scene_manager.async_save_scene(
        "Saved Banner",
        {"entry-1": {"type": "image_crop", "image_id": "img-1", "crop_box": [0.0, 0.0, 0.5, 1.0]}},
    )
    assert result["mappings"] == {
        "entry-1": {"type": "image_crop", "image_id": "img-1", "crop_box": [0.0, 0.0, 0.5, 1.0]}
    }


async def test_save_scene_rejects_image_crop_with_bad_crop_box(scene_manager):
    with pytest.raises(SceneError, match="Invalid crop_box"):
        await scene_manager.async_save_scene(
            "Bad", {"entry-1": {"type": "image_crop", "image_id": "img-1", "crop_box": [0.1, 0.2]}}
        )


async def test_send_mappings_image_crop_uses_override_and_bypasses_cache(
    hass, scene_manager, library_and_coordinators, monkeypatch
):
    """Two frames sharing one saved banner image at the *same* resolution
    but different crop_box_override values must never read back each
    other's cached bytes -- the exact collision library.py's per-
    resolution record.crops keying would otherwise cause (see
    library.async_get_bin_for_send's crop_box_override docstring)."""
    entries = library_and_coordinators(count=2)

    async def _fake_send(self, image_bytes, *, image_id=None, thumbnail=None):
        return {"success": True, "queued": False}

    from custom_components.digital_frames.coordinator import DigitalFramesCoordinator

    monkeypatch.setattr(DigitalFramesCoordinator, "async_send_image_or_queue", _fake_send)

    mappings = {
        entries[0].entry_id: {
            "type": "image_crop",
            "image_id": "banner-1",
            "crop_box": [0.0, 0.0, 0.5, 1.0],
        },
        entries[1].entry_id: {
            "type": "image_crop",
            "image_id": "banner-1",
            "crop_box": [0.5, 0.0, 1.0, 1.0],
        },
    }
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert all(r["success"] for r in result["results"])
    fake_library = hass.data[DOMAIN]["_library"]
    calls = sorted(fake_library.crop_box_override_calls)
    assert calls == [
        ("banner-1", (0.0, 0.0, 0.5, 1.0)),
        ("banner-1", (0.5, 0.0, 1.0, 1.0)),
    ]


async def test_send_mappings_image_crop_missing_fields_rejected(
    hass, scene_manager, library_and_coordinators
):
    entries = library_and_coordinators(count=1)
    mappings = {entries[0].entry_id: {"type": "image_crop", "image_id": "banner-1"}}
    result = await scene_manager.async_send_mappings(hass, mappings)

    assert result["results"][0]["success"] is False
    assert "Invalid mapping" in result["results"][0]["message"]
