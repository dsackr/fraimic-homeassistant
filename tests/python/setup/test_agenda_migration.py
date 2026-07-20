"""Migrate Daily Agenda widget → Live skill (Content Platform Phase 4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.digital_frames import _async_migrate_agenda_widget
from custom_components.digital_frames.const import DOMAIN


@pytest.mark.asyncio
async def test_migrate_agenda_widget_creates_skill_and_schedule(hass):
    saved = {}
    schedules = []

    async def _save_skill(name, content_mode, config, skill_id=None):
        saved["name"] = name
        saved["content_mode"] = content_mode
        saved["config"] = config
        saved["skill_id"] = skill_id or "daily_agenda"
        return {"skill_id": saved["skill_id"], "name": name}

    async def _create_schedule(name, action, trigger, enabled=True):
        schedules.append(
            {"name": name, "action": action, "trigger": trigger, "enabled": enabled}
        )
        return schedules[-1]

    skill_manager = SimpleNamespace(async_save_skill=_save_skill)
    schedule_manager = SimpleNamespace(async_create_schedule=_create_schedule)

    uninstalled = []

    async def _uninstall(pack_id):
        uninstalled.append(pack_id)
        del scene_pack_manager._installed[pack_id]

    scene_pack_manager = SimpleNamespace(
        _installed={
            "daily_agenda": {
                "type": "widget",
                "frame_id": "frame_1",
                "schedule": {"type": "daily", "time": "07:15:00"},
                "config": {
                    "calendar_source": "ha",
                    "ha_calendar_entities": "calendar.home,calendar.work",
                    "temp_unit": "celsius",
                },
            }
        },
        async_uninstall_pack=_uninstall,
        _cancel_scheduler=lambda *a: None,
        _async_persist=AsyncMock(),
    )

    await _async_migrate_agenda_widget(
        hass, skill_manager, schedule_manager, scene_pack_manager
    )

    assert saved["content_mode"] == "agenda"
    assert saved["config"]["calendar_source"] == "ha"
    assert saved["config"]["ha_calendar_entities"] == "calendar.home,calendar.work"
    assert saved["config"]["temp_unit"] == "celsius"
    assert len(schedules) == 1
    assert schedules[0]["action"] == {
        "type": "skill",
        "entry_id": "frame_1",
        "skill_id": "daily_agenda",
    }
    assert schedules[0]["trigger"] == {
        "type": "recurring",
        "freq": "daily",
        "time": "07:15",
    }
    assert uninstalled == ["daily_agenda"]
    assert "daily_agenda" not in scene_pack_manager._installed


@pytest.mark.asyncio
async def test_migrate_agenda_noop_without_widget(hass):
    skill_manager = SimpleNamespace(async_save_skill=AsyncMock())
    schedule_manager = SimpleNamespace(async_create_schedule=AsyncMock())
    scene_pack_manager = SimpleNamespace(_installed={})

    await _async_migrate_agenda_widget(
        hass, skill_manager, schedule_manager, scene_pack_manager
    )
    skill_manager.async_save_skill.assert_not_called()
    schedule_manager.async_create_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_widget_install_rejected(hass, aioclient_mock):
    from custom_components.digital_frames.const import SCENE_PACK_INDEX_URL
    from custom_components.digital_frames.scene_packs import (
        ScenePackError,
        ScenePackManager,
    )
    from custom_components.digital_frames.scenes import SceneManager

    class _FakeLibrary:
        async def async_upload(self, *a, **k):
            return {"image_id": "x"}

        async def async_list_images(self):
            return []

    mgr = ScenePackManager(hass, _FakeLibrary(), SceneManager(hass))
    aioclient_mock.get(
        SCENE_PACK_INDEX_URL,
        json={
            "packs": [
                {
                    "id": "daily_agenda",
                    "name": "Daily Agenda",
                    "type": "widget",
                    "script_url": "addons/daily_agenda/agenda_renderer.py",
                }
            ]
        },
    )
    with pytest.raises(ScenePackError, match="Live tab"):
        await mgr.async_install_pack("daily_agenda", config_data={"frame_id": "x"})
