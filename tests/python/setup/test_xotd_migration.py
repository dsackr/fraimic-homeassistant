"""One-time migration off the retired per-instance xOTD model into
frame-agnostic skills + general schedules (see __init__.py's
_async_migrate_xotd_instances).

If this silently breaks: upgrading users silently lose their xOTD content
instead of getting an equivalent skill+schedule, or migration re-runs on
every restart and duplicates records forever.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers.storage import Store

from custom_components.digital_frames import _async_migrate_xotd_instances
from custom_components.digital_frames.const import DOMAIN


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    class _FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            return {"battery": 90, "width": 1200, "height": 1600}

    class _FakeSession:
        def get(self, *a, **kw):
            return _FakeResponse()

        def post(self, *a, **kw):
            return _FakeResponse()

    monkeypatch.setattr(
        "custom_components.digital_frames.coordinator.async_get_clientsession",
        lambda hass: _FakeSession(),
    )


async def _seed_old_store(hass, instances, enabled=True):
    store = Store(hass, 1, f"{DOMAIN}_xotd")
    await store.async_save({"enabled": enabled, "instances": instances})
    return store


async def _setup_frame(hass, make_frame_entry, **kwargs):
    entry = make_frame_entry(**kwargs)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_daily_instance_migrates_to_skill_and_daily_schedule(
    hass, make_frame_entry
):
    await _seed_old_store(
        hass,
        [
            {
                "instance_id": "inst1",
                "content_mode": "joke",
                "frame_id": "e1",
                "schedule": {"type": "daily", "time": "07:30:00"},
                "mode_config": {"joke_feed": "icanhazdadjoke"},
                "enabled": True,
            }
        ],
    )
    await _setup_frame(hass, make_frame_entry, entry_id="e1")

    skill_manager = hass.data[DOMAIN]["_skills"]
    migrated = [
        s for s in await skill_manager.async_list_skills() if s["name"] == "Joke (migrated)"
    ]
    assert len(migrated) == 1
    assert migrated[0]["content_mode"] == "joke"
    assert migrated[0]["config"] == {"joke_feed": "icanhazdadjoke"}

    schedule_manager = hass.data[DOMAIN]["_schedules"]
    schedules = await schedule_manager.async_list_schedules()
    matching = [s for s in schedules if s["action"].get("skill_id") == migrated[0]["skill_id"]]
    assert len(matching) == 1
    assert matching[0]["action"] == {
        "type": "skill", "entry_id": "e1", "skill_id": migrated[0]["skill_id"],
    }
    # HH:MM:SS truncated to HH:MM for ScheduleManager's recurring trigger.
    assert matching[0]["trigger"] == {"type": "recurring", "freq": "daily", "time": "07:30"}


async def test_hourly_instance_migrates_to_hourly_recurring_schedule(
    hass, make_frame_entry
):
    await _seed_old_store(
        hass,
        [
            {
                "instance_id": "inst1",
                "content_mode": "word",
                "frame_id": "e1",
                "schedule": {"type": "hourly"},
                "mode_config": {},
                "enabled": True,
            }
        ],
    )
    await _setup_frame(hass, make_frame_entry, entry_id="e1")

    schedule_manager = hass.data[DOMAIN]["_schedules"]
    schedules = await schedule_manager.async_list_schedules()
    assert len(schedules) == 1
    assert schedules[0]["trigger"] == {"type": "recurring", "freq": "hourly"}


async def test_image_instance_migrates_sub_mode_to_content_mode(hass, make_frame_entry):
    await _seed_old_store(
        hass,
        [
            {
                "instance_id": "inst1",
                "content_mode": "image",
                "frame_id": "e1",
                "schedule": {"type": "hourly"},
                "mode_config": {"sub_mode": "image_album", "album": "Vacation"},
                "enabled": True,
            }
        ],
    )
    await _setup_frame(hass, make_frame_entry, entry_id="e1")

    skill_manager = hass.data[DOMAIN]["_skills"]
    skills = await skill_manager.async_list_skills()
    migrated = [s for s in skills if s["content_mode"] == "image_album"]
    assert len(migrated) == 1
    assert migrated[0]["config"] == {"album": "Vacation"}


async def test_migration_is_idempotent_across_restarts(hass, make_frame_entry):
    entry = await _setup_frame(hass, make_frame_entry, entry_id="e1")
    skill_manager = hass.data[DOMAIN]["_skills"]
    schedule_manager = hass.data[DOMAIN]["_schedules"]

    await _seed_old_store(
        hass,
        [
            {
                "instance_id": "inst1",
                "content_mode": "joke",
                "frame_id": entry.entry_id,
                "schedule": {"type": "hourly"},
                "mode_config": {},
                "enabled": True,
            }
        ],
    )

    await _async_migrate_xotd_instances(hass, skill_manager, schedule_manager)
    first_skill_count = len(await skill_manager.async_list_skills())
    first_schedule_count = len(await schedule_manager.async_list_schedules())

    # Simulating a second restart: the old store was cleared after the
    # first migration, so a second run must not create duplicates.
    await _async_migrate_xotd_instances(hass, skill_manager, schedule_manager)

    assert len(await skill_manager.async_list_skills()) == first_skill_count
    assert len(await schedule_manager.async_list_schedules()) == first_schedule_count


async def test_migration_with_no_old_instances_is_a_no_op(hass, make_frame_entry):
    entry = await _setup_frame(hass, make_frame_entry, entry_id="e1")
    skill_manager = hass.data[DOMAIN]["_skills"]
    schedule_manager = hass.data[DOMAIN]["_schedules"]

    before_skills = len(await skill_manager.async_list_skills())
    await _async_migrate_xotd_instances(hass, skill_manager, schedule_manager)
    assert len(await skill_manager.async_list_skills()) == before_skills
    assert await schedule_manager.async_list_schedules() == []
