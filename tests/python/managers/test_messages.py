"""Compose & send a styled text message: skills.py's ephemeral message
render methods (never a persisted Skill -- see module docstring in
skills.py and docs/KEY_PRODUCT_FLOWS.md).

If this silently breaks: a wall-banner send could re-render its shared
canvas once per frame instead of once (defeating the entire "render once,
crop many" premise this feature depends on), or a frame's slice of the
banner could come out misaligned.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.skills import SkillError, SkillManager
from custom_components.digital_frames.walls import WallManager

# Fakes mirror test_skills.py's (own copy, matching this suite's existing
# convention of each test file carrying its own small fakes rather than
# sharing them across modules with no __init__.py package structure).


class _FakeScenePacks:
    async def async_get_pack(self, pack_id):
        return None


class _FakeLibrary:
    def __init__(self):
        self.uploads = []

    async def async_list_images(self):
        return []

    async def async_upload(self, filename, raw_bytes, albums=None):
        record = {
            "image_id": f"uploaded_{len(self.uploads)}",
            "filename": filename,
            "albums": list(albums or []),
        }
        self.uploads.append(record)
        return record


class _FakeProcess:
    def __init__(self, returncode=0, stdout=b"rendered ok", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
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
    """Every message render fetches the pinned xOTD renderer script over
    HTTP first (see SkillManager._async_script_bytes) -- register that
    response so tests exercising the render path don't hit a real network
    call."""
    from custom_components.digital_frames.const import (
        XOTD_RENDERER_PINNED_BASE,
        XOTD_RENDERER_SCRIPT_PATH,
    )

    script_url = f"{XOTD_RENDERER_PINNED_BASE}/{XOTD_RENDERER_SCRIPT_PATH}"
    aioclient_mock.get(script_url, content=b"fake-script-bytes")
    return aioclient_mock


async def _make_wall(hass, placements: dict) -> str:
    wall_manager = WallManager(hass)
    await wall_manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_walls"] = wall_manager
    saved = await wall_manager.async_save_wall("Test Wall", placements)
    return saved["wall_id"]


def _write_bin_and_preview(run_dir: str, width: int, height: int, color=(10, 20, 30)):
    from PIL import Image
    import io

    with open(os.path.join(run_dir, "xotd.bin"), "wb") as f:
        f.write(bytes((width * height) // 2))
    rgb = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    with open(os.path.join(run_dir, "xotd_preview.png"), "wb") as f:
        f.write(buf.getvalue())


# ---------------------------------------------------------------------------
# Single-frame / scene-member rendering
# ---------------------------------------------------------------------------


async def test_render_message_for_entry_returns_bin_and_preview(
    hass, skill_manager, make_frame_entry, monkeypatch, mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")  # 1200x1600 default
    entry.add_to_hass(hass)

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        _write_bin_and_preview(run_dir, 1200, 1600)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    result = await skill_manager.async_render_message_for_entry(
        "Happy Birthday!", "plain", entry
    )
    assert result["kind"] == "bin"
    assert result["preview"][:8] == b"\x89PNG\r\n\x1a\n"


async def test_render_message_script_config_carries_text_and_style(
    hass, skill_manager, make_frame_entry, monkeypatch, mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)

    captured = {}

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        import json

        with open(config_path) as f:
            captured["config"] = json.load(f)
        _write_bin_and_preview(run_dir, 1200, 1600)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    await skill_manager.async_render_message_for_entry("Dinner's ready!", "ad_50s", entry)
    assert captured["config"]["content_mode"] == "message"
    assert captured["config"]["message_text"] == "Dinner's ready!"
    assert captured["config"]["style"] == "ad_50s"


async def test_render_message_nonzero_exit_raises_skill_error(
    hass, skill_manager, make_frame_entry, monkeypatch, mock_script_download,
):
    entry = make_frame_entry(entry_id="e1")
    entry.add_to_hass(hass)

    async def _fake_exec(*args, **kwargs):
        return _FakeProcess(returncode=1, stderr=b"boom")

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    with pytest.raises(SkillError, match="boom"):
        await skill_manager.async_render_message_for_entry("Hi", "plain", entry)


async def test_render_message_canvas_returns_rgb_png_bytes(
    hass, skill_manager, monkeypatch, mock_script_download,
):
    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        _write_bin_and_preview(run_dir, 2400, 1600)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    rgb_png = await skill_manager.async_render_message_canvas("Hi", "plain", 2400, 1600)
    assert rgb_png[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Wall-banner crop rendering: the shared-canvas de-dup is the load-bearing
# behavior this whole feature depends on.
# ---------------------------------------------------------------------------


async def test_wall_crop_renders_canvas_once_for_concurrent_frames(
    hass, skill_manager, make_frame_entry, monkeypatch, mock_script_download,
):
    """N frames in one wall-banner send must trigger exactly ONE subprocess
    render of the shared canvas, not N -- scenes.py resolves every mapping
    in a wall send concurrently (asyncio.gather), so without de-duping the
    in-flight render task, every frame's call would race past a naive
    cache-miss check and each would spawn its own redundant render,
    defeating "render once, crop many" entirely."""
    entries = []
    for i, x in enumerate((0.0, 1200.0, 2400.0)):
        entry = make_frame_entry(entry_id=f"e{i}", width=1200, height=1600)
        entry.add_to_hass(hass)
        entries.append((entry, x))
    placements = {entry.entry_id: {"x": x, "y": 0.0} for entry, x in entries}
    wall_id = await _make_wall(hass, placements)

    exec_calls = []

    async def _fake_exec(*args, **kwargs):
        exec_calls.append(args)
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        # Simulate slow rendering so all three concurrent calls are
        # in-flight together before any of them finishes.
        await asyncio.sleep(0.02)
        _write_bin_and_preview(run_dir, 1200 * 3, 1600)
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    results = await asyncio.gather(
        *(
            skill_manager.async_render_message_wall_crop_for_entry(
                "Happy Birthday!", "plain", wall_id, entry
            )
            for entry, _ in entries
        )
    )

    assert len(exec_calls) == 1  # exactly one render for all three frames
    assert all(r["kind"] == "bin" for r in results)


async def test_wall_crop_uses_distinct_crop_per_frame(
    hass, skill_manager, make_frame_entry, monkeypatch, mock_script_download,
):
    e0 = make_frame_entry(entry_id="e0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="e1", width=1200, height=1600)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall_id = await _make_wall(
        hass, {"e0": {"x": 0.0, "y": 0.0}, "e1": {"x": 1200.0, "y": 0.0}}
    )

    async def _fake_exec(*args, **kwargs):
        config_path = args[4]
        run_dir = os.path.dirname(config_path)
        # Left half red, right half blue -- so each frame's crop produces
        # visibly (and byte-wise) different output; a uniform-color canvas
        # would pack identically regardless of which half was cropped.
        from PIL import Image
        import io

        canvas = Image.new("RGB", (2400, 1600), (0, 0, 0))
        canvas.paste(Image.new("RGB", (1200, 1600), (178, 19, 24)), (0, 0))
        canvas.paste(Image.new("RGB", (1200, 1600), (33, 87, 186)), (1200, 0))
        with open(os.path.join(run_dir, "xotd.bin"), "wb") as f:
            f.write(bytes((2400 * 1600) // 2))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        with open(os.path.join(run_dir, "xotd_preview.png"), "wb") as f:
            f.write(buf.getvalue())
        return _FakeProcess(returncode=0)

    monkeypatch.setattr(
        "custom_components.digital_frames.skills.asyncio.create_subprocess_exec", _fake_exec
    )

    result0 = await skill_manager.async_render_message_wall_crop_for_entry(
        "Hi", "plain", wall_id, e0
    )
    result1 = await skill_manager.async_render_message_wall_crop_for_entry(
        "Hi", "plain", wall_id, e1
    )
    # Different crop slices of the same canvas -> different wire bytes.
    assert result0["bytes"] != result1["bytes"]


async def test_wall_crop_unknown_wall_raises_skill_error(
    hass, skill_manager, make_frame_entry,
):
    hass.data.setdefault(DOMAIN, {})["_walls"] = WallManager(hass)
    entry = make_frame_entry(entry_id="e0")
    entry.add_to_hass(hass)

    with pytest.raises(SkillError, match="not found"):
        await skill_manager.async_render_message_wall_crop_for_entry(
            "Hi", "plain", "no-such-wall", entry
        )


async def test_wall_crop_invalid_geometry_raises_skill_error(
    hass, skill_manager, make_frame_entry,
):
    e0 = make_frame_entry(entry_id="e0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="e1", width=800, height=480)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall_id = await _make_wall(
        hass, {"e0": {"x": 0.0, "y": 0.0}, "e1": {"x": 1200.0, "y": 0.0}}
    )

    with pytest.raises(SkillError, match="same resolution"):
        await skill_manager.async_render_message_wall_crop_for_entry(
            "Hi", "plain", wall_id, e0
        )
