"""Schedules: send a scene or image at a future/recurring time (KPF 20).

If this silently breaks: missed schedules never fire after an outage, or a
schedule keeps trying to fire against a deleted target forever instead of
showing "broken" in the UI.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.schedules import (
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_TARGET_MISSING,
    ScheduleError,
    ScheduleManager,
)
from homeassistant.util import dt as dt_util


class _FakeSceneManager:
    def __init__(self):
        self.scenes = {}
        self.sent = []

    async def async_send_mappings(self, hass, mappings):
        self.sent.append(dict(mappings))
        return {"results": [{"entry_id": k, "success": True} for k in mappings]}


class _FakeScene:
    def __init__(self, scene_id, mappings):
        self.scene_id = scene_id
        self.mappings = mappings


class _FakeLibrary:
    def __init__(self, image_ids):
        self.image_ids = set(image_ids)

    async def async_list_images(self):
        return [{"image_id": i} for i in self.image_ids]


class _FakeSkillManager:
    def __init__(self, skill_ids):
        self.skill_ids = set(skill_ids)

    async def async_get_skill(self, skill_id):
        return {"skill_id": skill_id} if skill_id in self.skill_ids else None


@pytest.fixture(autouse=True)
async def _utc_time_zone(hass):
    # Recurrence math below freezes wall-clock times as naive UTC strings --
    # pin hass's configured time zone so dt_util.now() matches them exactly
    # regardless of the machine running the tests.
    await hass.config.async_set_time_zone("UTC")


@pytest.fixture
def schedule_manager(hass):
    return ScheduleManager(hass)


@pytest.fixture
def fake_scene_manager(hass):
    mgr = _FakeSceneManager()
    hass.data.setdefault(DOMAIN, {})["_scenes"] = mgr
    return mgr


@pytest.fixture
def fake_library(hass):
    lib = _FakeLibrary(image_ids=set())
    hass.data.setdefault(DOMAIN, {})["_library"] = lib
    return lib


@pytest.fixture
def fake_skill_manager(hass):
    mgr = _FakeSkillManager(skill_ids=set())
    hass.data.setdefault(DOMAIN, {})["_skills"] = mgr
    return mgr


# ---------------------------------------------------------------------------
# Trigger/action validation
# ---------------------------------------------------------------------------


async def test_create_once_in_the_past_rejected(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    past = (dt_util.now() - timedelta(hours=1)).isoformat()
    with pytest.raises(ScheduleError, match="must be in the future"):
        await schedule_manager.async_create_schedule(
            "Test", {"type": "scene", "scene_id": "s1"}, {"type": "once", "at": past}
        )


async def test_create_once_in_the_future_succeeds(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    future = (dt_util.now() + timedelta(hours=1)).isoformat()
    result = await schedule_manager.async_create_schedule(
        "Test", {"type": "scene", "scene_id": "s1"}, {"type": "once", "at": future}
    )
    assert result["status"] == STATUS_PENDING


async def test_weekly_requires_at_least_one_day(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    with pytest.raises(ScheduleError, match="at least one weekday"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "scene", "scene_id": "s1"},
            {"type": "recurring", "freq": "weekly", "time": "09:00", "days": []},
        )


async def test_monthly_requires_day_of_month(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    with pytest.raises(ScheduleError, match="day_of_month"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "scene", "scene_id": "s1"},
            {"type": "recurring", "freq": "monthly", "time": "09:00"},
        )


async def test_invalid_recurrence_freq_rejected(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    with pytest.raises(ScheduleError, match="Invalid recurrence"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "scene", "scene_id": "s1"},
            {"type": "recurring", "freq": "yearly", "time": "09:00"},
        )


async def test_hourly_recurrence_accepted_with_no_time(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    schedule = await schedule_manager.async_create_schedule(
        "Test", {"type": "scene", "scene_id": "s1"}, {"type": "recurring", "freq": "hourly"}
    )
    assert schedule["trigger"] == {"type": "recurring", "freq": "hourly"}


async def test_create_scene_action_target_missing_rejected(schedule_manager, fake_scene_manager):
    future = (dt_util.now() + timedelta(hours=1)).isoformat()
    with pytest.raises(ScheduleError, match="scene no longer exists"):
        await schedule_manager.async_create_schedule(
            "Test", {"type": "scene", "scene_id": "gone"}, {"type": "once", "at": future}
        )


async def test_create_image_action_requires_entry_and_image(schedule_manager):
    with pytest.raises(ScheduleError, match="entry_id and an image_id"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "image", "entry_id": "", "image_id": "img1"},
            {"type": "recurring", "freq": "daily", "time": "09:00"},
        )


async def test_create_skill_action_requires_entry_and_skill(schedule_manager):
    with pytest.raises(ScheduleError, match="entry_id and a skill_id"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "skill", "entry_id": "", "skill_id": "word_of_the_day"},
            {"type": "recurring", "freq": "daily", "time": "09:00"},
        )


async def test_create_skill_action_missing_frame_rejected(
    schedule_manager, fake_skill_manager
):
    fake_skill_manager.skill_ids = {"word_of_the_day"}
    with pytest.raises(ScheduleError, match="frame is no longer configured"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "skill", "entry_id": "never-configured", "skill_id": "word_of_the_day"},
            {"type": "recurring", "freq": "daily", "time": "09:00"},
        )


async def test_create_skill_action_missing_skill_rejected(
    hass, schedule_manager, fake_skill_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    with pytest.raises(ScheduleError, match="skill no longer exists"):
        await schedule_manager.async_create_schedule(
            "Test",
            {"type": "skill", "entry_id": "e1", "skill_id": "does-not-exist"},
            {"type": "recurring", "freq": "daily", "time": "09:00"},
        )


async def test_skill_action_fires_through_scene_manager_with_skill_mapping(
    hass, schedule_manager, fake_scene_manager, fake_skill_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_skill_manager.skill_ids = {"word_of_the_day"}

    created = await schedule_manager.async_create_schedule(
        "Word of the Day",
        {"type": "skill", "entry_id": "e1", "skill_id": "word_of_the_day"},
        {"type": "recurring", "freq": "hourly"},
    )
    schedule = schedule_manager._schedules[created["schedule_id"]]
    await schedule_manager._async_fire(schedule)

    assert fake_scene_manager.sent == [
        {"e1": {"type": "skill", "skill_id": "word_of_the_day"}}
    ]


# ---------------------------------------------------------------------------
# Missed one-shot fires late on restart
# ---------------------------------------------------------------------------


async def test_missed_once_fires_late(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    past = (dt_util.now() - timedelta(hours=1)).isoformat()
    created = await schedule_manager.async_create_schedule(
        "Test", {"type": "scene", "scene_id": "s1"}, {"type": "once", "at": (dt_util.now() + timedelta(hours=1)).isoformat()}
    )
    # Force the stored trigger into the past to simulate "was due while HA
    # was down" without going through create's require_future validation.
    schedule = schedule_manager._schedules[created["schedule_id"]]
    schedule.trigger["at"] = past

    await schedule_manager._async_fire_missed()

    updated = await schedule_manager.async_get_schedule(created["schedule_id"])
    assert updated.status == STATUS_COMPLETED
    assert updated.fired_late is True
    assert fake_scene_manager.sent == [{"e1": "i1"}]


async def test_pending_future_once_not_fired_as_missed(schedule_manager, fake_scene_manager):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "i1"})
    future = (dt_util.now() + timedelta(hours=1)).isoformat()
    created = await schedule_manager.async_create_schedule(
        "Test", {"type": "scene", "scene_id": "s1"}, {"type": "once", "at": future}
    )

    await schedule_manager._async_fire_missed()

    assert fake_scene_manager.sent == []
    updated = await schedule_manager.async_get_schedule(created["schedule_id"])
    assert updated.status == STATUS_PENDING


# ---------------------------------------------------------------------------
# Recurring fire re-resolves the scene at fire time, not creation time
# ---------------------------------------------------------------------------


async def test_recurring_fire_resolves_scene_mappings_at_fire_time(
    schedule_manager, fake_scene_manager
):
    fake_scene_manager.scenes["s1"] = _FakeScene("s1", {"e1": "original-image"})
    created = await schedule_manager.async_create_schedule(
        "Daily",
        {"type": "scene", "scene_id": "s1"},
        {"type": "recurring", "freq": "daily", "time": "09:00"},
    )

    # Scene edited after the schedule was created.
    fake_scene_manager.scenes["s1"].mappings = {"e1": "updated-image"}

    schedule = schedule_manager._schedules[created["schedule_id"]]
    await schedule_manager._async_fire(schedule)

    assert fake_scene_manager.sent == [{"e1": "updated-image"}]


# ---------------------------------------------------------------------------
# Target deleted at fire time -> target_missing + disabled
# ---------------------------------------------------------------------------


async def test_fire_with_deleted_image_target_marks_target_missing(
    hass, schedule_manager, fake_scene_manager, fake_library, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.image_ids = {"img1"}

    created = await schedule_manager.async_create_schedule(
        "Daily",
        {"type": "image", "entry_id": "e1", "image_id": "img1"},
        {"type": "recurring", "freq": "daily", "time": "09:00"},
    )

    # Image removed from the library before the schedule fires.
    fake_library.image_ids = set()

    schedule = schedule_manager._schedules[created["schedule_id"]]
    await schedule_manager._async_fire(schedule)

    updated = await schedule_manager.async_get_schedule(created["schedule_id"])
    assert updated.status == STATUS_TARGET_MISSING
    assert updated.enabled is False
    assert fake_scene_manager.sent == []


async def test_fire_with_deleted_skill_target_marks_target_missing(
    hass, schedule_manager, fake_scene_manager, fake_skill_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_skill_manager.skill_ids = {"word_of_the_day"}

    created = await schedule_manager.async_create_schedule(
        "Word of the Day",
        {"type": "skill", "entry_id": "e1", "skill_id": "word_of_the_day"},
        {"type": "recurring", "freq": "daily", "time": "09:00"},
    )

    # Skill deleted before the schedule fires.
    fake_skill_manager.skill_ids = set()

    schedule = schedule_manager._schedules[created["schedule_id"]]
    await schedule_manager._async_fire(schedule)

    updated = await schedule_manager.async_get_schedule(created["schedule_id"])
    assert updated.status == STATUS_TARGET_MISSING
    assert updated.enabled is False
    assert fake_scene_manager.sent == []


async def test_handle_skill_deleted_disables_referencing_schedules(
    hass, schedule_manager, fake_scene_manager, fake_skill_manager, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_skill_manager.skill_ids = {"word_of_the_day"}

    created = await schedule_manager.async_create_schedule(
        "Word of the Day",
        {"type": "skill", "entry_id": "e1", "skill_id": "word_of_the_day"},
        {"type": "recurring", "freq": "daily", "time": "09:00"},
    )

    await schedule_manager.async_handle_skill_deleted("word_of_the_day")

    updated = await schedule_manager.async_get_schedule(created["schedule_id"])
    assert updated.status == STATUS_TARGET_MISSING
    assert updated.enabled is False


async def test_edit_resets_broken_schedule_to_pending(
    hass, schedule_manager, fake_scene_manager, fake_library, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.image_ids = {"img1"}
    created = await schedule_manager.async_create_schedule(
        "Daily",
        {"type": "image", "entry_id": "e1", "image_id": "img1"},
        {"type": "recurring", "freq": "daily", "time": "09:00"},
    )
    fake_library.image_ids = set()
    schedule = schedule_manager._schedules[created["schedule_id"]]
    await schedule_manager._async_fire(schedule)
    assert schedule.status == STATUS_TARGET_MISSING

    fake_library.image_ids = {"img2"}
    updated = await schedule_manager.async_update_schedule(
        created["schedule_id"],
        {"action": {"type": "image", "entry_id": "e1", "image_id": "img2"}},
    )
    assert updated["status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# next_fire_at recurrence math
# ---------------------------------------------------------------------------


def _schedule(trigger, enabled=True, status=STATUS_PENDING):
    from custom_components.digital_frames.schedules import Schedule

    return Schedule(
        {
            "schedule_id": "x",
            "name": "x",
            "enabled": enabled,
            "status": status,
            "action": {"type": "scene", "scene_id": "s1"},
            "trigger": trigger,
        }
    )


async def test_next_fire_at_daily_today_if_still_ahead(schedule_manager, freezer):
    freezer.move_to("2026-04-15 08:00:00")
    schedule = _schedule({"type": "recurring", "freq": "daily", "time": "09:00"})
    next_fire = schedule_manager.next_fire_at(schedule)
    assert next_fire.startswith("2026-04-15T09:00:00")


async def test_next_fire_at_daily_rolls_to_tomorrow_if_passed(schedule_manager, freezer):
    freezer.move_to("2026-04-15 10:00:00")
    schedule = _schedule({"type": "recurring", "freq": "daily", "time": "09:00"})
    next_fire = schedule_manager.next_fire_at(schedule)
    assert next_fire.startswith("2026-04-16T09:00:00")


async def test_next_fire_at_monthly_clamps_31st_in_april(schedule_manager, freezer):
    freezer.move_to("2026-04-15 08:00:00")
    schedule = _schedule(
        {"type": "recurring", "freq": "monthly", "time": "10:00", "day_of_month": 31}
    )
    next_fire = schedule_manager.next_fire_at(schedule)
    assert next_fire.startswith("2026-04-30T10:00:00")


async def test_next_fire_at_weekly_finds_next_matching_day(schedule_manager, freezer):
    # 2026-04-15 is a Wednesday (weekday()==2); ask for Friday (4).
    freezer.move_to("2026-04-15 08:00:00")
    schedule = _schedule(
        {"type": "recurring", "freq": "weekly", "time": "09:00", "days": [4]}
    )
    next_fire = schedule_manager.next_fire_at(schedule)
    assert next_fire.startswith("2026-04-17T09:00:00")


async def test_next_fire_at_disabled_schedule_returns_none(schedule_manager):
    schedule = _schedule(
        {"type": "recurring", "freq": "daily", "time": "09:00"}, enabled=False
    )
    assert schedule_manager.next_fire_at(schedule) is None


async def test_next_fire_at_broken_schedule_returns_none(schedule_manager):
    schedule = _schedule(
        {"type": "recurring", "freq": "daily", "time": "09:00"},
        status=STATUS_TARGET_MISSING,
    )
    assert schedule_manager.next_fire_at(schedule) is None
