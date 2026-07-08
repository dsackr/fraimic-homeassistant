"""Scheduled events: send a scene (or a single image to a single frame) at
a future moment -- a calendar date/time or a daily/weekly/monthly
recurrence.

A schedule owns *when* and *what*; it never owns *how*. Firing resolves the
action to plain (entry_id -> image_id) mappings at fire time and hands them
to SceneManager.async_send_mappings -- the same single executor every other
send path terminates in -- so queue/bump semantics come for free and exist
in exactly one place. Creating a schedule touches nothing on any frame.

Like scenes and walls, schedules are pure local state (entry_ids are
meaningless off this HA instance), persisted in their own Store.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_SCHEDULES_UPDATED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}_schedules"
_STORAGE_VERSION = 1

# Completed one-shots are kept around as history for the calendar popup,
# then purged on load once they're this old.
_COMPLETED_RETENTION = timedelta(days=30)

_FREQS = ("daily", "weekly", "monthly")

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_TARGET_MISSING = "target_missing"


class ScheduleError(Exception):
    """Raised for invalid schedule operations (bad trigger/action, not found)."""


def _parse_local_at(at: Any) -> datetime:
    """Parse a stored/submitted `once` datetime into an aware local datetime.

    The panel submits the user's wall-clock intent as a naive local ISO
    string (what <input type="datetime-local"> produces); dt_util.as_local
    attaches HA's configured timezone to a naive value.
    """
    if not isinstance(at, str) or (parsed := dt_util.parse_datetime(at)) is None:
        raise ScheduleError(f"Invalid datetime: {at!r}")
    return dt_util.as_local(parsed)


def _parse_hhmm(value: Any) -> tuple[int, int]:
    try:
        hour_s, minute_s = str(value).split(":")
        hour, minute = int(hour_s), int(minute_s)
    except (TypeError, ValueError) as err:
        raise ScheduleError(f"Invalid time: {value!r} (expected HH:MM)") from err
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"Invalid time: {value!r} (expected HH:MM)")
    return hour, minute


def _clamped_day(dt: datetime, day_of_month: int) -> int:
    """The day this monthly schedule fires in dt's month: day_of_month,
    clamped to the month's last day so 'the 31st' works in April."""
    return min(day_of_month, calendar.monthrange(dt.year, dt.month)[1])


class Schedule:
    """One scheduled event. Plain dict-backed record (see the PRD's record
    shape) rather than a dataclass: trigger/action are shape-validated
    unions, not flat fields."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.schedule_id: str = data["schedule_id"]
        self.name: str = data["name"]
        self.enabled: bool = bool(data.get("enabled", True))
        self.action: dict[str, Any] = dict(data["action"])
        self.trigger: dict[str, Any] = dict(data["trigger"])
        self.created_at: str = data.get("created_at") or dt_util.now().isoformat()
        self.last_fired_at: str | None = data.get("last_fired_at")
        self.status: str = data.get("status", STATUS_PENDING)
        self.fired_late: bool = bool(data.get("fired_late", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "enabled": self.enabled,
            "action": self.action,
            "trigger": self.trigger,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
            "status": self.status,
            "fired_late": self.fired_late,
        }


def _validate_trigger(trigger: Any, *, require_future: bool) -> dict[str, Any]:
    """Normalise and validate a trigger union; returns the cleaned dict."""
    if not isinstance(trigger, dict):
        raise ScheduleError("Trigger must be an object")
    ttype = trigger.get("type")
    if ttype == "once":
        at = _parse_local_at(trigger.get("at"))
        if require_future and at <= dt_util.now():
            raise ScheduleError("Scheduled time must be in the future")
        return {"type": "once", "at": trigger["at"]}
    if ttype == "recurring":
        freq = trigger.get("freq")
        if freq not in _FREQS:
            raise ScheduleError(f"Invalid recurrence: {freq!r} (daily/weekly/monthly)")
        _parse_hhmm(trigger.get("time"))
        cleaned: dict[str, Any] = {
            "type": "recurring", "freq": freq, "time": trigger["time"],
        }
        if freq == "weekly":
            days = trigger.get("days")
            if (
                not isinstance(days, list)
                or not days
                or not all(isinstance(d, int) and 0 <= d <= 6 for d in days)
            ):
                raise ScheduleError("Weekly schedules need at least one weekday (0-6)")
            cleaned["days"] = sorted(set(days))
        elif freq == "monthly":
            dom = trigger.get("day_of_month")
            if not isinstance(dom, int) or not 1 <= dom <= 31:
                raise ScheduleError("Monthly schedules need a day_of_month (1-31)")
            cleaned["day_of_month"] = dom
        return cleaned
    raise ScheduleError(f"Invalid trigger type: {ttype!r}")


def _validate_action_shape(action: Any) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ScheduleError("Action must be an object")
    atype = action.get("type")
    if atype == "scene":
        if not action.get("scene_id"):
            raise ScheduleError("Scene actions need a scene_id")
        return {"type": "scene", "scene_id": action["scene_id"]}
    if atype == "image":
        if not action.get("entry_id") or not action.get("image_id"):
            raise ScheduleError("Image actions need an entry_id and an image_id")
        return {
            "type": "image",
            "entry_id": action["entry_id"],
            "image_id": action["image_id"],
        }
    raise ScheduleError(f"Invalid action type: {atype!r}")


class ScheduleManager:
    """Owns the set of scheduled events and their armed HA timers."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._schedules: dict[str, Schedule] = {}
        # schedule_id -> timer unsubscribe. Same lifecycle discipline as
        # ScenePackManager._schedulers: cancel per-schedule on edit/delete/
        # disable, all-at-once in unload().
        self._schedulers: dict[str, Any] = {}
        self._started_unsub: Any = None

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        purged = False
        cutoff = dt_util.now() - _COMPLETED_RETENTION
        for data in (stored or {}).get("schedules", []):
            try:
                schedule = Schedule(data)
            except KeyError:
                _LOGGER.warning("Dropping malformed stored schedule: %s", data)
                purged = True
                continue
            if schedule.status == STATUS_COMPLETED and schedule.last_fired_at:
                fired = dt_util.parse_datetime(schedule.last_fired_at)
                if fired is not None and dt_util.as_local(fired) < cutoff:
                    purged = True
                    continue
            self._schedules[schedule.schedule_id] = schedule
        if purged:
            await self._async_persist()

        for schedule in self._schedules.values():
            self._arm(schedule)

        # Missed one-shots (HA was down at fire time) fire on startup --
        # late is better than never for art on a wall. Deferred until HA
        # has started so every frame's coordinator exists; firing from
        # async_setup would find no coordinators at all.
        if self.hass.state is CoreState.running:
            self.hass.async_create_task(self._async_fire_missed())
        else:
            self._started_unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_on_started
            )

    async def _async_on_started(self, _event: Any) -> None:
        self._started_unsub = None
        await self._async_fire_missed()

    async def _async_fire_missed(self) -> None:
        now = dt_util.now()
        for schedule in list(self._schedules.values()):
            if (
                schedule.enabled
                and schedule.status == STATUS_PENDING
                and schedule.trigger.get("type") == "once"
            ):
                try:
                    at = _parse_local_at(schedule.trigger.get("at"))
                except ScheduleError:
                    continue
                if at <= now:
                    _LOGGER.info(
                        "Schedule '%s' was due at %s while Home Assistant was "
                        "down -- firing late now",
                        schedule.name,
                        schedule.trigger.get("at"),
                    )
                    await self._async_fire(schedule, late=True)

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"schedules": [s.to_dict() for s in self._schedules.values()]}
        )

    def _signal(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_SCHEDULES_UPDATED)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def async_list_schedules(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._schedules.values()]

    async def async_get_schedule(self, schedule_id: str) -> Schedule | None:
        return self._schedules.get(schedule_id)

    async def async_validate_target(self, action: dict[str, Any]) -> None:
        """Raise ScheduleError unless the action's target exists right now.
        Creation/edit-time only -- fire time re-resolves on its own and
        degrades to target_missing instead of raising."""
        if action["type"] == "scene":
            scene_manager = self.hass.data.get(DOMAIN, {}).get("_scenes")
            if scene_manager is None or scene_manager.scenes.get(action["scene_id"]) is None:
                raise ScheduleError("That scene no longer exists")
            return
        entry = self.hass.config_entries.async_get_entry(action["entry_id"])
        if entry is None or entry.domain != DOMAIN:
            raise ScheduleError("That frame is no longer configured")
        library = self.hass.data.get(DOMAIN, {}).get("_library")
        if library is None:
            raise ScheduleError("Library manager not initialised")
        images = await library.async_list_images()
        if not any(img.get("image_id") == action["image_id"] for img in images):
            raise ScheduleError("That image is no longer in the library")

    async def async_create_schedule(
        self,
        name: str,
        action: Any,
        trigger: Any,
        enabled: bool = True,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ScheduleError("Schedule name can't be empty")
        action = _validate_action_shape(action)
        trigger = _validate_trigger(trigger, require_future=True)
        await self.async_validate_target(action)

        schedule = Schedule(
            {
                "schedule_id": uuid.uuid4().hex[:12],
                "name": name,
                "enabled": bool(enabled),
                "action": action,
                "trigger": trigger,
                "created_at": dt_util.now().isoformat(),
            }
        )
        self._schedules[schedule.schedule_id] = schedule
        self._arm(schedule)
        await self._async_persist()
        self._signal()
        return schedule.to_dict()

    async def async_update_schedule(
        self, schedule_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge *changes* (any of name/action/trigger/enabled) onto an
        existing schedule and re-arm. Editing the action or trigger resets
        a completed/target_missing record back to pending -- that's how a
        user repairs a broken schedule from the calendar popup."""
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            raise ScheduleError(f"Schedule '{schedule_id}' not found")

        if "name" in changes:
            name = (changes["name"] or "").strip()
            if not name:
                raise ScheduleError("Schedule name can't be empty")
            schedule.name = name
        if "enabled" in changes:
            schedule.enabled = bool(changes["enabled"])

        retriggered = False
        if "action" in changes:
            action = _validate_action_shape(changes["action"])
            await self.async_validate_target(action)
            schedule.action = action
            retriggered = True
        if "trigger" in changes:
            schedule.trigger = _validate_trigger(changes["trigger"], require_future=True)
            retriggered = True
        if retriggered:
            schedule.status = STATUS_PENDING
            schedule.fired_late = False

        self._arm(schedule)
        await self._async_persist()
        self._signal()
        return schedule.to_dict()

    async def async_delete_schedule(self, schedule_id: str) -> None:
        if schedule_id in self._schedules:
            self._disarm(schedule_id)
            del self._schedules[schedule_id]
            await self._async_persist()
            self._signal()

    async def async_handle_scene_deleted(self, scene_id: str) -> None:
        """Disable (not delete) every schedule referencing a just-deleted
        scene and mark it target_missing -- the calendar popup then shows
        the user what broke instead of the schedule silently vanishing."""
        broken = [
            s
            for s in self._schedules.values()
            if s.action.get("type") == "scene"
            and s.action.get("scene_id") == scene_id
            and s.status != STATUS_COMPLETED
        ]
        if not broken:
            return
        for schedule in broken:
            _LOGGER.warning(
                "Scene referenced by schedule '%s' was deleted -- disabling "
                "the schedule",
                schedule.name,
            )
            schedule.status = STATUS_TARGET_MISSING
            schedule.enabled = False
            self._disarm(schedule.schedule_id)
        await self._async_persist()
        self._signal()

    # ------------------------------------------------------------------
    # Arming / firing
    # ------------------------------------------------------------------

    def _arm(self, schedule: Schedule) -> None:
        self._disarm(schedule.schedule_id)
        if not schedule.enabled or schedule.status != STATUS_PENDING:
            return

        schedule_id = schedule.schedule_id
        trigger = schedule.trigger

        async def _fire(_now: datetime) -> None:
            # Re-fetch: the record may have been edited/deleted since arming
            # (its timer would have been cancelled, but be defensive).
            current = self._schedules.get(schedule_id)
            if current is None or not current.enabled:
                return
            await self._async_fire(current)

        if trigger.get("type") == "once":
            try:
                at = _parse_local_at(trigger.get("at"))
            except ScheduleError:
                _LOGGER.warning(
                    "Schedule '%s' has an unparseable time -- not arming", schedule.name
                )
                return
            if at <= dt_util.now():
                # Missed while HA was down; _async_fire_missed handles it.
                return
            self._schedulers[schedule_id] = async_track_point_in_time(
                self.hass, _fire, at
            )
            return

        # recurring: a wall-clock daily timer (HA handles DST); weekly and
        # monthly filter inside the callback.
        freq = trigger.get("freq")
        hour, minute = _parse_hhmm(trigger.get("time"))

        async def _maybe_fire(now: datetime) -> None:
            today = dt_util.now()
            if freq == "weekly" and today.weekday() not in trigger.get("days", []):
                return
            if freq == "monthly" and today.day != _clamped_day(
                today, trigger.get("day_of_month", 1)
            ):
                return
            await _fire(now)

        self._schedulers[schedule_id] = async_track_time_change(
            self.hass, _maybe_fire, hour=hour, minute=minute, second=0
        )

    def _disarm(self, schedule_id: str) -> None:
        unsub = self._schedulers.pop(schedule_id, None)
        if unsub is not None:
            unsub()

    def unload(self) -> None:
        """Cancel every armed timer and the deferred-startup listener."""
        for schedule_id in list(self._schedulers):
            self._disarm(schedule_id)
        if self._started_unsub is not None:
            self._started_unsub()
            self._started_unsub = None

    async def _async_resolve_mappings(
        self, schedule: Schedule
    ) -> dict[str, str] | None:
        """The action's (entry_id -> image_id) mappings as of *right now*,
        or None if the target is gone. Scenes resolve at fire time, so
        editing a scene updates what its schedules send."""
        action = schedule.action
        if action.get("type") == "scene":
            scene_manager = self.hass.data.get(DOMAIN, {}).get("_scenes")
            scene = (
                scene_manager.scenes.get(action.get("scene_id"))
                if scene_manager is not None
                else None
            )
            return dict(scene.mappings) if scene is not None else None

        entry_id, image_id = action.get("entry_id"), action.get("image_id")
        if self.hass.config_entries.async_get_entry(entry_id) is None:
            return None
        library = self.hass.data.get(DOMAIN, {}).get("_library")
        if library is not None:
            try:
                images = await library.async_list_images()
            except Exception:  # noqa: BLE001
                # Transient backend error (e.g. Dropbox hiccup) must not
                # brand the schedule target_missing; let the send attempt
                # surface any real failure per-mapping instead.
                pass
            else:
                if not any(img.get("image_id") == image_id for img in images):
                    return None
        return {entry_id: image_id}

    async def _async_fire(self, schedule: Schedule, *, late: bool = False) -> None:
        mappings = await self._async_resolve_mappings(schedule)
        if not mappings:
            _LOGGER.warning(
                "Schedule '%s' fired but its target no longer exists -- "
                "disabling it",
                schedule.name,
            )
            schedule.status = STATUS_TARGET_MISSING
            schedule.enabled = False
            self._disarm(schedule.schedule_id)
            await self._async_persist()
            self._signal()
            return

        # Record the firing *before* the send: if HA dies mid-send, a once
        # schedule must not re-fire on the next startup (double e-ink
        # redraws are the thing this integration goes out of its way to
        # avoid).
        schedule.last_fired_at = dt_util.now().isoformat()
        schedule.fired_late = late
        if schedule.trigger.get("type") == "once":
            schedule.status = STATUS_COMPLETED
            self._disarm(schedule.schedule_id)
        await self._async_persist()
        self._signal()

        scene_manager = self.hass.data.get(DOMAIN, {}).get("_scenes")
        if scene_manager is None:
            _LOGGER.error(
                "Schedule '%s' fired but the scene manager is missing", schedule.name
            )
            return
        try:
            result = await scene_manager.async_send_mappings(self.hass, mappings)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Schedule '%s' failed to send: %s", schedule.name, err)
            return
        results = result.get("results", [])
        failures = [r for r in results if not r.get("success") and not r.get("queued")]
        queued = [r for r in results if r.get("queued")]
        _LOGGER.info(
            "Schedule '%s' fired: %d sent, %d queued for wake, %d failed%s",
            schedule.name,
            len(results) - len(failures) - len(queued),
            len(queued),
            len(failures),
            f" ({failures})" if failures else "",
        )

    # ------------------------------------------------------------------
    # Recurrence math (for the HTTP layer's computed next_fire_at)
    # ------------------------------------------------------------------

    def next_fire_at(self, schedule: Schedule) -> str | None:
        """ISO local datetime of the next firing, or None for disabled /
        completed / broken schedules. Computed here so the panel never
        re-implements recurrence math."""
        if not schedule.enabled or schedule.status != STATUS_PENDING:
            return None
        trigger = schedule.trigger
        now = dt_util.now()

        if trigger.get("type") == "once":
            try:
                at = _parse_local_at(trigger.get("at"))
            except ScheduleError:
                return None
            return at.isoformat() if at > now else None

        try:
            hour, minute = _parse_hhmm(trigger.get("time"))
        except ScheduleError:
            return None
        freq = trigger.get("freq")
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if freq == "daily":
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.isoformat()

        if freq == "weekly":
            days = trigger.get("days") or []
            if not days:
                return None
            for offset in range(8):
                attempt = candidate + timedelta(days=offset)
                if attempt.weekday() in days and attempt > now:
                    return attempt.isoformat()
            return None

        if freq == "monthly":
            dom = trigger.get("day_of_month", 1)
            for month_offset in range(2):
                year = now.year + (now.month - 1 + month_offset) // 12
                month = (now.month - 1 + month_offset) % 12 + 1
                anchor = now.replace(year=year, month=month, day=1)
                attempt = anchor.replace(
                    day=_clamped_day(anchor, dom),
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )
                if attempt > now:
                    return attempt.isoformat()
            return None

        return None
