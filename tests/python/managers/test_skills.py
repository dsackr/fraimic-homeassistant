"""Skills: frame-agnostic content presets, CRUD + on-demand rendering.

If this silently breaks: a fan-out to several frames re-fetches non-date-
seeded content per frame (showing different content on each "of the day"
send); concurrent renders of the same skill clobber each other's
config.json/xotd.bin; a render failure crashes instead of degrading to a
per-mapping failure.

Text-mode (joke/quote/scripture/word) rendering subprocess-execs a script --
like scene_packs.py's widget execution and xotd.py's old per-instance
execution, the actual subprocess is faked here (see _FakeProcess) rather
than really invoking python3, matching this suite's existing carve-out for
subprocess-based execution (see test_scene_packs.py's module docstring).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.skills import SkillError, SkillManager

_XOTD_PACK = {
    "id": "xotd",
    "script_url": "addons/xotd/xotd_renderer.py",
    "config_schema": [
        {"name": "content_mode"},
        {"name": "theme"},
        {"name": "drop_cap"},
        {"name": "joke_feed"},
        {"name": "quote_feed"},
        {"name": "word_feed"},
        {"name": "bible_translation"},
        {"name": "scripture_source"},
    ],
}


class _FakeScenePacks:
    def __init__(self, pack=None):
        self.pack = pack or dict(_XOTD_PACK)
        self.get_pack_calls = 0

    async def async_get_pack(self, pack_id):
        self.get_pack_calls += 1
        assert pack_id == "xotd"
        return self.pack


class _FakeLibrary:
    def __init__(self, images=None):
        self.images = images or []
        self.uploads = []

    async def async_list_images(self):
        return list(self.images)

    async def async_upload(self, filename, raw_bytes, albums=None):
        record = {"image_id": f"uploaded_{len(self.uploads)}", "filename": filename, "albums": list(albums or [])}
        self.uploads.append(record)
        return record


class _FakeProcess:
    def __init__(self, returncode=0, stdout=b"rendered ok", stderr=b"", hang=False):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


@pytest.fixture
def fake_scene_packs():
    return _FakeScenePacks()


@pytest.fixture
def fake_library():
    return _FakeLibrary()


@pytest.fixture
def skill_manager(hass, fake_library, fake_scene_packs):
    return SkillManager(hass, fake_library, fake_scene_packs)


@pytest.fixture
def mock_script_download(aioclient_mock):
    """Every text-mode render fetches the renderer script over HTTP first
    (see SkillManager._async_script_bytes) -- register that response so
    tests exercising the render path don't hit a real network call."""
    from custom_components.fraimic.const import (
        XOTD_RENDERER_PINNED_BASE,
        XOTD_RENDERER_SCRIPT_PATH,
    )

    script_url = f"{XOTD_RENDERER_PINNED_BASE}/{XOTD_RENDERER_SCRIPT_PATH}"
    aioclient_mock.get(script_url, content=b"fake-script-bytes")
    return aioclient_mock


def _fake_subprocess_exec_writing_bin(bin_bytes=b"fake-bin-bytes", **process_kwargs):
    """A fake asyncio.create_subprocess_exec that writes *bin_bytes* to the
    xotd.bin path the real renderer would have written, next to the
    --config path it's invoked with (args[4])."""

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        with open(os.path.join(run_dir, "xotd.bin"), "wb") as f:
            f.write(bin_bytes)
        return _FakeProcess(**process_kwargs)

    return _fake_exec


# ---------------------------------------------------------------------------
# CRUD + built-in seeding
# ---------------------------------------------------------------------------


async def test_built_in_skills_seeded_on_first_load(skill_manager):
    await skill_manager.async_load()
    skills = await skill_manager.async_list_skills()
    names = {s["name"] for s in skills}
    assert names == {"Word of the Day", "Joke of the Day", "Quote of the Day", "Scripture of the Day"}


async def test_built_ins_not_reseeded_after_user_deletes_one(hass, fake_library, fake_scene_packs):
    first = SkillManager(hass, fake_library, fake_scene_packs)
    await first.async_load()
    skills = await first.async_list_skills()
    await first.async_delete_skill(skills[0]["skill_id"])

    second = SkillManager(hass, fake_library, fake_scene_packs)
    await second.async_load()
    assert len(await second.async_list_skills()) == 3


async def test_create_custom_skill(skill_manager):
    await skill_manager.async_load()
    result = await skill_manager.async_save_skill("My Joke", "joke", {"joke_feed": "icanhazdadjoke"})
    assert result["name"] == "My Joke"
    assert result["content_mode"] == "joke"


async def test_name_collision_with_builtin_gets_disambiguated(skill_manager):
    await skill_manager.async_load()
    result = await skill_manager.async_save_skill("Word of the Day", "word", {})
    assert result["name"] == "Word of the Day (2)"


async def test_update_existing_skill(skill_manager):
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom", "joke", {"joke_feed": "icanhazdadjoke"})
    updated = await skill_manager.async_save_skill(
        "Renamed", "quote", {"quote_feed": "zenquotes"}, skill_id=created["skill_id"]
    )
    assert updated["skill_id"] == created["skill_id"]
    assert updated["name"] == "Renamed"
    assert updated["content_mode"] == "quote"


async def test_update_of_deleted_skill_fails_cleanly(skill_manager):
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Temp", "joke", {})
    await skill_manager.async_delete_skill(created["skill_id"])
    with pytest.raises(SkillError, match="not found"):
        await skill_manager.async_save_skill("Temp2", "joke", {}, skill_id=created["skill_id"])


async def test_invalid_content_mode_rejected(skill_manager):
    await skill_manager.async_load()
    with pytest.raises(SkillError, match="Invalid content_mode"):
        await skill_manager.async_save_skill("Bad", "carrier_pigeon", {})


async def test_image_feed_requires_known_provider(skill_manager):
    await skill_manager.async_load()
    with pytest.raises(SkillError, match="feed_provider"):
        await skill_manager.async_save_skill(
            "Feed", "image_feed", {"feed_provider": "carrier_pigeon"}
        )


async def test_image_album_requires_album_name(skill_manager):
    await skill_manager.async_load()
    with pytest.raises(SkillError, match="needs an album"):
        await skill_manager.async_save_skill("Album", "image_album", {})


async def test_deleting_skill_disarms_referencing_schedules(hass, skill_manager):
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom", "joke", {})

    calls = []

    class _FakeScheduleManager:
        async def async_handle_skill_deleted(self, skill_id):
            calls.append(skill_id)

    hass.data.setdefault(DOMAIN, {})["_schedules"] = _FakeScheduleManager()

    await skill_manager.async_delete_skill(created["skill_id"])
    assert calls == [created["skill_id"]]


# ---------------------------------------------------------------------------
# Rendering: image_feed / image_album (fully in-process, no subprocess)
# ---------------------------------------------------------------------------


async def test_image_album_render_picks_from_named_album(
    hass, skill_manager, fake_library, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.images = [
        {"image_id": "img1", "albums": ["Vacation"]},
        {"image_id": "img2", "albums": ["Family"]},
    ]
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill(
        "Vacation Rotation", "image_album", {"album": "Vacation"}
    )

    result = await skill_manager.async_render_for_entry(created["skill_id"], entry)
    assert result == {"kind": "image_id", "image_id": "img1"}


async def test_image_album_with_no_matching_images_raises(
    hass, skill_manager, fake_library, make_frame_entry
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    fake_library.images = [{"image_id": "img1", "albums": ["Family"]}]
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill(
        "Vacation Rotation", "image_album", {"album": "Vacation"}
    )

    with pytest.raises(SkillError, match="no images"):
        await skill_manager.async_render_for_entry(created["skill_id"], entry)


async def test_image_feed_uploads_tagged_and_returns_image_id(
    hass, skill_manager, fake_library, make_frame_entry, aioclient_mock
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    aioclient_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image", "url": "https://example.com/apod.jpg", "date": "2026-01-01"},
    )
    aioclient_mock.get("https://example.com/apod.jpg", content=b"fake-jpeg-bytes")

    await skill_manager.async_load()
    created = await skill_manager.async_save_skill(
        "APOD", "image_feed", {"feed_provider": "nasa_apod"}
    )

    result = await skill_manager.async_render_for_entry(created["skill_id"], entry)
    assert result["kind"] == "image_id"
    assert fake_library.uploads[0]["albums"] == ["Image of the Day"]
    assert result["image_id"] == fake_library.uploads[0]["image_id"]


async def test_image_feed_non_image_apod_raises(
    hass, skill_manager, fake_library, make_frame_entry, aioclient_mock
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    aioclient_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "video", "url": "https://example.com/apod.mp4", "date": "2026-01-01"},
    )
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill(
        "APOD", "image_feed", {"feed_provider": "nasa_apod"}
    )

    with pytest.raises(SkillError, match="not an image"):
        await skill_manager.async_render_for_entry(created["skill_id"], entry)
    assert fake_library.uploads == []


# ---------------------------------------------------------------------------
# Rendering: text modes (subprocess faked, see _FakeProcess)
# ---------------------------------------------------------------------------


async def test_text_render_returns_bin_bytes_and_cleans_up_run_dir(
    hass, skill_manager, make_frame_entry, monkeypatch,
    mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom Word", "word", {"word_feed": "custom"})

    captured_run_dir = {}

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        captured_run_dir["path"] = run_dir
        with open(os.path.join(run_dir, "xotd.bin"), "wb") as f:
            f.write(b"fake-bin-bytes")
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("custom_components.fraimic.skills.asyncio.create_subprocess_exec", _fake_exec)

    result = await skill_manager.async_render_for_entry(created["skill_id"], entry)
    assert result == {"kind": "bin", "bytes": b"fake-bin-bytes"}
    assert not os.path.exists(captured_run_dir["path"])  # cleaned up after


async def test_text_render_nonzero_exit_raises_skill_error(
    hass, skill_manager, make_frame_entry, monkeypatch,
    mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom Word", "word", {"word_feed": "custom"})

    async def _fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=1, stderr=b"boom")

    monkeypatch.setattr("custom_components.fraimic.skills.asyncio.create_subprocess_exec", _fake_exec)

    with pytest.raises(SkillError, match="boom"):
        await skill_manager.async_render_for_entry(created["skill_id"], entry)


async def test_text_render_timeout_raises_and_kills_process(
    hass, skill_manager, make_frame_entry, monkeypatch,
    mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom Word", "word", {"word_feed": "custom"})

    fake_process = _FakeProcess(hang=True)

    async def _fake_exec(*args, **kwargs):
        return fake_process

    monkeypatch.setattr("custom_components.fraimic.skills.asyncio.create_subprocess_exec", _fake_exec)
    monkeypatch.setattr("custom_components.fraimic.skills._RENDER_TIMEOUT", 0.05)

    with pytest.raises(SkillError, match="timed out"):
        await skill_manager.async_render_for_entry(created["skill_id"], entry)
    assert fake_process.killed is True


async def test_concurrent_renders_of_same_skill_use_isolated_run_dirs(
    hass, skill_manager, make_frame_entry, monkeypatch,
    mock_script_download,
):
    """Two renders of the same skill_id at once must not collide on a
    shared config.json/xotd.bin (see module docstring)."""
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom Word", "word", {"word_feed": "custom"})

    seen_run_dirs = []

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        seen_run_dirs.append(run_dir)
        # Simulate slow rendering so both invocations are in-flight together.
        await asyncio.sleep(0.02)
        with open(os.path.join(run_dir, "xotd.bin"), "wb") as f:
            f.write(f"bin-for-{run_dir}".encode())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr("custom_components.fraimic.skills.asyncio.create_subprocess_exec", _fake_exec)

    results = await asyncio.gather(
        skill_manager.async_render_for_entry(created["skill_id"], entry),
        skill_manager.async_render_for_entry(created["skill_id"], entry),
    )

    assert len(set(seen_run_dirs)) == 2  # each render got its own directory
    assert results[0]["bytes"] != results[1]["bytes"]  # each read back its own bin


async def test_content_fields_cached_across_renders_same_day(
    hass, skill_manager, fake_scene_packs, make_frame_entry, monkeypatch,
    mock_script_download,
):
    """A fan-out of a skill to multiple frames must reuse one fetched
    content payload -- otherwise a non-date-seeded feed (joke/word) could
    show different content on each frame in the same send."""
    entry_a = make_frame_entry(entry_id="e1")
    entry_a.add_to_hass(hass)
    entry_b = make_frame_entry(entry_id="e2")
    entry_b.add_to_hass(hass)
    await skill_manager.async_load()
    created = await skill_manager.async_save_skill("Custom Word", "word", {"word_feed": "custom"})

    monkeypatch.setattr(
        "custom_components.fraimic.skills.asyncio.create_subprocess_exec",
        _fake_subprocess_exec_writing_bin(),
    )

    await skill_manager.async_render_for_entry(created["skill_id"], entry_a)
    calls_after_first = fake_scene_packs.get_pack_calls
    await skill_manager.async_render_for_entry(created["skill_id"], entry_b)

    # Content fields are cached per (skill, day) -- the second render (same
    # skill, same day) must not re-fetch the catalog pack for its
    # config_schema again (script bytes caching is covered separately, see
    # test_script_bytes_cached_across_calls -- that fetch no longer
    # consults the catalog pack at all, see _async_script_bytes).
    assert fake_scene_packs.get_pack_calls == calls_after_first


async def test_script_bytes_cached_across_calls(
    hass, skill_manager, aioclient_mock
):
    from custom_components.fraimic.const import (
        XOTD_RENDERER_PINNED_BASE,
        XOTD_RENDERER_SCRIPT_PATH,
    )

    await skill_manager.async_load()
    script_url = f"{XOTD_RENDERER_PINNED_BASE}/{XOTD_RENDERER_SCRIPT_PATH}"
    aioclient_mock.get(script_url, content=b"fake-script-bytes")

    first_bytes = await skill_manager._async_script_bytes()
    assert first_bytes == b"fake-script-bytes"

    second_bytes = await skill_manager._async_script_bytes()
    assert second_bytes == first_bytes
    # The TTL cache short-circuits before ever re-fetching -- aioclient_mock
    # only has one registered response, so a second real request would
    # raise "No mock registered".
    assert len(aioclient_mock.mock_calls) == 1
