"""Skills: frame-agnostic, on-demand-renderable content presets (Word of the
Day, Joke of the Day, Quote of the Day, Scripture of the Day, or a rotating
photo feed/album) -- the frame-agnostic counterpart to a library image_id.

A skill owns *what* content to generate, never *which* frame it goes to or
*when* -- that's supplied by whoever asks for a render: a wall/scene mapping
entry (see Scene.mappings in scenes.py), a schedule's "skill" action (see
schedules.py), the fraimic.send_skill service, or the FraimicSendSkill voice
intent. This mirrors how a library image_id works today, just with the bytes
generated per-request instead of stored.

Two execution paths, dispatched by content_mode at render time -- the same
split the retired XotdManager used (see git history: xotd.py):
  - joke/quote/scripture/word ("text" modes): the frame-addons renderer
    script is downloaded from a *pinned* commit (XOTD_RENDERER_PINNED_BASE
    in const.py -- deliberately not the scene-pack catalog's main-tracking
    script_url, since this depends on that exact commit's --render-only/
    --config CLI contract) and cached (see _async_script_bytes), then run
    as a subprocess with --render-only in a fresh per-render temp
    directory, so concurrent renders (e.g. one skill mapped to five frames
    in a single scene send) never collide on the same config.json/xotd.bin.
    The resulting Spectra .bin is read back and re-encoded for the target
    panel codec (pass-through for Fraimic; unpack→JPEG for Meural) via
    panel_codec.text_skill_payload_for_codec.
  - image_feed/image_album: no script, no subprocess -- a web feed (NASA
    APOD / Wikimedia Picture of the Day / Bing wallpaper) is fetched
    directly and imported into the photo library, or an existing photo is
    picked at random from a user-chosen album; either way the result is a
    library image_id, resolved by the caller exactly like any other scene
    mapping.

A short content cache (keyed by skill_id + local date) avoids re-fetching a
non-date-seeded feed (icanhazdadjoke, random-word-api) once per frame when
one skill fans out to several frames at once -- without it, "Joke of the
Day" mapped to five frames in one scene could show five different jokes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shutil
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SIGNAL_SKILLS_UPDATED,
    XOTD_RENDERER_PINNED_BASE,
    XOTD_RENDERER_SCRIPT_PATH,
)
from .panel_codec import panel_codec_for_resolution

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .library import LibraryManager
    from .scene_packs import ScenePackManager

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}_skills"
_STORAGE_VERSION = 1

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)
_RENDER_TIMEOUT = 45  # seconds -- one hung subprocess fails just its own mapping, not a whole fan-out

_TEXT_CONTENT_MODES = ("joke", "quote", "scripture", "word")
_IMAGE_SUB_MODES = ("image_feed", "image_album")
_CONTENT_MODES = _TEXT_CONTENT_MODES + _IMAGE_SUB_MODES
_IMAGE_FEED_PROVIDERS = ("nasa_apod", "wikimedia_potd", "bing_wallpaper")
_IMAGE_OTD_ALBUM = "Image of the Day"

_SCRIPT_CACHE_TTL = 3600  # seconds -- the renderer script changes far less often than the pack catalog
_CONTENT_CACHE_TTL = 1800  # seconds -- a fan-out to N frames within this window reuses one fetch

# Seeded once, on first load, before any XotdInstance migration runs -- so a
# migrated instance's name never collides silently with one of these (see
# SkillManager._unique_name).
_BUILTIN_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "skill_id": "word_of_the_day",
        "name": "Word of the Day",
        "content_mode": "word",
        "config": {"word_feed": "random_word"},
    },
    {
        "skill_id": "joke_of_the_day",
        "name": "Joke of the Day",
        "content_mode": "joke",
        "config": {"joke_feed": "icanhazdadjoke"},
    },
    {
        "skill_id": "quote_of_the_day",
        "name": "Quote of the Day",
        "content_mode": "quote",
        "config": {"quote_feed": "zenquotes"},
    },
    {
        "skill_id": "scripture_of_the_day",
        "name": "Scripture of the Day",
        "content_mode": "scripture",
        "config": {"bible_translation": "niv", "scripture_source": "daily_api"},
    },
)


class SkillError(Exception):
    """Raised for invalid skill operations (bad shape, not found) and for
    render failures (script/network/subprocess) -- callers resolving a
    single mapping (SceneManager.async_send_mappings) catch this and turn
    it into a per-mapping failure, same as any other resolution error."""


def _validate_mode_config(content_mode: str, mode_config: Any) -> dict[str, Any]:
    """Text modes accept whatever the xotd catalog pack's own config_schema
    collected -- validated generically by the panel's schema-driven form,
    not re-validated field-by-field here. Image sub-modes have no catalog
    backing, so they're validated explicitly."""
    mode_config = dict(mode_config) if isinstance(mode_config, dict) else {}
    if content_mode not in _IMAGE_SUB_MODES:
        return mode_config
    if content_mode == "image_feed":
        provider = mode_config.get("feed_provider")
        if provider not in _IMAGE_FEED_PROVIDERS:
            raise SkillError(f"Invalid feed_provider: {provider!r}")
    else:  # image_album
        if not mode_config.get("album"):
            raise SkillError("image_album mode needs an album")
    return mode_config


@dataclass
class Skill:
    """A named (content_mode, config) content preset -- no frame, no
    schedule; those are supplied by whoever renders it."""

    skill_id: str
    name: str
    content_mode: str
    config: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "content_mode": self.content_mode,
            "config": self.config,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            content_mode=data["content_mode"],
            config=dict(data.get("config") or {}),
            created_at=data.get("created_at", 0.0),
        )


class SkillManager:
    """Owns the set of skills, plus the renderer-script and fetched-content
    caches shared across every render (see module docstring)."""

    def __init__(
        self,
        hass: "HomeAssistant",
        library: "LibraryManager",
        scene_packs: "ScenePackManager",
    ) -> None:
        self.hass = hass
        self._library = library
        self._scene_packs = scene_packs
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._skills: dict[str, Skill] = {}
        self._script_cache: bytes | None = None
        self._script_cache_time: float = 0.0
        # (skill_id, local_date) -> (fields, fetched_at); see
        # _async_fetch_content_fields.
        self._content_cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        for data in (stored or {}).get("skills", []):
            try:
                skill = Skill.from_dict(data)
            except KeyError:
                _LOGGER.warning("Dropping malformed stored skill: %s", data)
                continue
            self._skills[skill.skill_id] = skill

        if not self._skills:
            for builtin in _BUILTIN_SKILLS:
                skill = Skill(
                    skill_id=builtin["skill_id"],
                    name=builtin["name"],
                    content_mode=builtin["content_mode"],
                    config=dict(builtin["config"]),
                    created_at=time.time(),
                )
                self._skills[skill.skill_id] = skill
            await self._async_persist()

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"skills": [skill.to_dict() for skill in self._skills.values()]}
        )

    def _signal(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_SKILLS_UPDATED)

    @property
    def skills(self) -> dict[str, Skill]:
        """Synchronous read-only view, mirroring SceneManager.scenes."""
        return self._skills

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def async_list_skills(self) -> list[dict[str, Any]]:
        return [skill.to_dict() for skill in self._skills.values()]

    async def async_get_skill(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    async def async_get_skill_by_name(self, name: str) -> Skill | None:
        name = (name or "").strip().lower()
        for skill in self._skills.values():
            if skill.name.strip().lower() == name:
                return skill
        return None

    def _unique_name(self, name: str, *, skill_id: str | None) -> str:
        """*name*, disambiguated with a " (2)", " (3)", ... suffix if it
        collides with another skill's name (built-in or not) -- so a
        migrated instance or a hand-typed name never silently overwrites an
        existing skill's identity."""
        existing_names = {
            skill.name.strip().lower()
            for skill in self._skills.values()
            if skill.skill_id != skill_id
        }
        candidate = name
        suffix = 1
        while candidate.strip().lower() in existing_names:
            suffix += 1
            candidate = f"{name} ({suffix})"
        return candidate

    async def async_save_skill(
        self,
        name: str,
        content_mode: str,
        config: Any,
        skill_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new skill (skill_id=None) or update an existing one."""
        name = (name or "").strip()
        if not name:
            raise SkillError("Skill name can't be empty")
        if content_mode not in _CONTENT_MODES:
            raise SkillError(f"Invalid content_mode: {content_mode!r}")
        config = _validate_mode_config(content_mode, config)

        if skill_id is not None and skill_id not in self._skills:
            raise SkillError(f"Skill '{skill_id}' not found")

        name = self._unique_name(name, skill_id=skill_id)

        if skill_id is not None:
            skill = self._skills[skill_id]
            skill.name = name
            skill.content_mode = content_mode
            skill.config = config
        else:
            skill = Skill(
                skill_id=uuid.uuid4().hex[:12],
                name=name,
                content_mode=content_mode,
                config=config,
                created_at=time.time(),
            )
            self._skills[skill.skill_id] = skill

        await self._async_persist()
        self._signal()
        return skill.to_dict()

    async def async_delete_skill(self, skill_id: str) -> None:
        if skill_id in self._skills:
            del self._skills[skill_id]
            await self._async_persist()
            self._signal()
            # Any schedule pointing at this skill is now broken -- disable
            # it and mark it target_missing, same treatment
            # SceneManager.async_delete_scene gives a deleted scene.
            schedule_manager = self.hass.data.get(DOMAIN, {}).get("_schedules")
            if schedule_manager is not None:
                await schedule_manager.async_handle_skill_deleted(skill_id)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    async def _async_script_bytes(self) -> bytes:
        """Fetch the xOTD renderer script from its pinned commit (see
        XOTD_RENDERER_PINNED_BASE) -- NOT from the scene-pack catalog's own
        (main-tracking) script_url field, since this method's caller
        depends on that exact commit's CLI contract (--render-only,
        --config) rather than whatever happens to be on main right now."""
        now = time.time()
        if (
            self._script_cache is not None
            and now - self._script_cache_time < _SCRIPT_CACHE_TTL
        ):
            return self._script_cache

        script_url = f"{XOTD_RENDERER_PINNED_BASE}/{XOTD_RENDERER_SCRIPT_PATH}"
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(script_url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    raise SkillError(f"HTTP {resp.status} fetching renderer script")
                script_content = await resp.read()
        except aiohttp.ClientError as err:
            raise SkillError(f"Failed to fetch renderer script: {err}") from err

        self._script_cache = script_content
        self._script_cache_time = now
        return script_content

    async def _async_fetch_content_fields(self, skill: Skill) -> dict[str, Any]:
        """The mode_config fields the xotd catalog pack's schema declares
        for this skill's content_mode, memoized per (skill, local day) so
        every render of this skill within _CONTENT_CACHE_TTL gets the SAME
        fetched content -- see module docstring (fan-out consistency)."""
        cache_key = (skill.skill_id, dt_util.now().strftime("%Y-%m-%d"))
        cached = self._content_cache.get(cache_key)
        now = time.time()
        if cached is not None and now - cached[1] < _CONTENT_CACHE_TTL:
            return cached[0]

        pack = await self._scene_packs.async_get_pack("xotd")
        fields: dict[str, Any] = {"content_mode": skill.content_mode}
        for field_def in pack.get("config_schema", []):
            field_name = field_def["name"]
            if field_name == "content_mode":
                continue
            val = skill.config.get(field_name)
            if field_def.get("type") == "json" and val:
                try:
                    val = json.loads(val)
                except (TypeError, ValueError):
                    val = None
            if val is not None:
                fields[field_name] = val

        self._content_cache[cache_key] = (fields, now)
        return fields

    async def _async_render_text(self, skill: Skill, entry: "ConfigEntry") -> bytes:
        script_content = await self._async_script_bytes()
        content_fields = await self._async_fetch_content_fields(skill)

        from .helpers import render_spec_for_entry  # noqa: PLC0415

        spec = render_spec_for_entry(entry)
        try:
            layout = panel_codec_for_resolution(spec.width, spec.height).byte_layout
        except ValueError:
            layout = "split_half"

        script_config: dict[str, Any] = {
            "frame": {"resolution": [spec.width, spec.height], "layout": layout},
            **content_fields,
        }

        # Fresh directory per render (not per skill_id): a skill fanned out
        # to several frames at once (or two schedules firing near
        # simultaneously) must never share a config.json/xotd.bin, or
        # concurrent renders clobber each other's files.
        run_dir = self.hass.config.path(
            "fraimic_addons", f"skill_{skill.skill_id}", f"run_{uuid.uuid4().hex[:8]}"
        )

        def _write_inputs() -> tuple[str, str]:
            os.makedirs(run_dir, exist_ok=True)
            script_path = os.path.join(run_dir, "renderer.py")
            with open(script_path, "wb") as f:
                f.write(script_content)
            config_path = os.path.join(run_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(script_config, f)
            return script_path, config_path

        try:
            script_path, config_path = await self.hass.async_add_executor_job(
                _write_inputs
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    script_path,
                    "--render-only",
                    "--config",
                    config_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=run_dir,
                )
            except Exception as err:  # noqa: BLE001
                raise SkillError(f"Failed to start renderer: {err}") from err

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=_RENDER_TIMEOUT
                )
            except asyncio.TimeoutError as err:
                process.kill()
                await process.communicate()
                raise SkillError(f"Rendering '{skill.name}' timed out") from err

            if process.returncode != 0:
                raise SkillError(
                    f"Rendering '{skill.name}' failed: {stderr.decode().strip()}"
                )
            _LOGGER.debug(
                "Skill '%s' rendered: %s", skill.name, stdout.decode().strip()
            )

            bin_path = os.path.join(run_dir, "xotd.bin")

            def _read_bin() -> bytes:
                with open(bin_path, "rb") as f:
                    return f.read()

            return await self.hass.async_add_executor_job(_read_bin)
        finally:
            await self.hass.async_add_executor_job(shutil.rmtree, run_dir, True)

    async def _async_fetch_image_feed(self, skill: Skill) -> str:
        provider = skill.config.get("feed_provider")
        session = async_get_clientsession(self.hass)
        today = dt_util.now()

        try:
            if provider == "nasa_apod":
                api_key = skill.config.get("nasa_api_key") or "DEMO_KEY"
                async with session.get(
                    "https://api.nasa.gov/planetary/apod",
                    params={"api_key": api_key},
                    timeout=_FETCH_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        raise SkillError(f"NASA APOD HTTP {resp.status}")
                    data = await resp.json()
                if data.get("media_type") != "image":
                    raise SkillError(
                        f"Today's APOD is not an image (media_type={data.get('media_type')})"
                    )
                image_url = data.get("hdurl") or data.get("url")
                filename = f"apod_{data.get('date', today.strftime('%Y-%m-%d'))}.jpg"

            elif provider == "wikimedia_potd":
                url = (
                    "https://en.wikipedia.org/api/rest_v1/feed/featured/"
                    f"{today.strftime('%Y/%m/%d')}"
                )
                async with session.get(url, timeout=_FETCH_TIMEOUT) as resp:
                    if resp.status != 200:
                        raise SkillError(f"Wikimedia POTD HTTP {resp.status}")
                    data = await resp.json()
                image = (data.get("image") or {}).get("image") or {}
                image_url = image.get("source")
                if not image_url:
                    raise SkillError("Wikimedia POTD response missing an image")
                basename = os.path.basename(urllib.parse.urlparse(image_url).path)
                filename = basename or f"wikimedia_potd_{today.strftime('%Y-%m-%d')}.jpg"

            elif provider == "bing_wallpaper":
                async with session.get(
                    "https://www.bing.com/HPImageArchive.aspx",
                    params={"format": "js", "idx": "0", "n": "1", "mkt": "en-US"},
                    timeout=_FETCH_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        raise SkillError(f"Bing wallpaper HTTP {resp.status}")
                    data = await resp.json()
                images = data.get("images") or []
                if not images:
                    raise SkillError("Bing wallpaper response had no images")
                image_url = f"https://www.bing.com{images[0]['url']}"
                filename = (
                    f"bing_wallpaper_{images[0].get('startdate', today.strftime('%Y%m%d'))}.jpg"
                )

            else:
                raise SkillError(f"Unknown feed_provider: {provider!r}")

            async with session.get(image_url, timeout=_DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    raise SkillError(f"HTTP {resp.status} downloading image")
                image_bytes = await resp.read()
        except aiohttp.ClientError as err:
            raise SkillError(f"Failed to fetch {provider} feed: {err}") from err

        record = await self._library.async_upload(
            filename, image_bytes, albums=[_IMAGE_OTD_ALBUM]
        )
        return record["image_id"]

    async def _async_pick_image_album(self, skill: Skill) -> str:
        album = skill.config.get("album")
        images = await self._library.async_list_images()
        candidates = [img for img in images if album in (img.get("albums") or [])]
        if not candidates:
            raise SkillError(f"Album '{album}' has no images")
        return random.choice(candidates)["image_id"]

    async def async_render_for_entry(
        self, skill_id: str, entry: "ConfigEntry"
    ) -> dict[str, Any]:
        """Render *skill_id* for *entry*'s resolution/layout.

        Returns {"kind": "bin", "bytes": ..., "preview": png_bytes|None} for
        text modes or {"kind": "image_id", "image_id": ...} for image
        sub-modes. Raises SkillError on any failure -- callers
        (SceneManager.async_send_mappings) catch this and turn it into a
        per-mapping failure, exactly like any other resolution error (e.g. a
        deleted library image).
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            raise SkillError(f"Skill '{skill_id}' not found")

        if skill.content_mode == "image_feed":
            image_id = await self._async_fetch_image_feed(skill)
            return {"kind": "image_id", "image_id": image_id}
        if skill.content_mode == "image_album":
            image_id = await self._async_pick_image_album(skill)
            return {"kind": "image_id", "image_id": image_id}

        bin_bytes = await self._async_render_text(skill, entry)

        # Text renderer always emits Spectra .bin. Re-encode for the target
        # panel codec (JPEG for Meural; Spectra pass-through for Fraimic) and
        # build a preview PNG so last_thumbnail survives the send.
        from .helpers import render_spec_for_entry  # noqa: PLC0415
        from .panel_codec import (  # noqa: PLC0415
            panel_codec_for_entry,
            text_skill_payload_for_codec,
        )

        spec = render_spec_for_entry(entry)
        try:
            codec_id = panel_codec_for_entry(entry).id
        except ValueError:
            codec_id = None

        try:
            wire_bytes, preview = await self.hass.async_add_executor_job(
                text_skill_payload_for_codec,
                bin_bytes,
                spec.width,
                spec.height,
                spec.rotation,
                codec_id,
            )
        except Exception as err:  # noqa: BLE001
            # Spectra: unpack/preview failures are soft (return raw bin).
            # JPEG: unpack is required — surface as SkillError.
            from .panel_codec import CODEC_JPEG_Q90  # noqa: PLC0415

            if codec_id == CODEC_JPEG_Q90:
                raise SkillError(
                    f"Could not encode skill '{skill.name}' for JPEG panel: {err}"
                ) from err
            _LOGGER.debug(
                "Could not build preview for skill '%s' render: %s",
                skill.name,
                err,
            )
            wire_bytes, preview = bin_bytes, None

        return {"kind": "bin", "bytes": wire_bytes, "preview": preview}
