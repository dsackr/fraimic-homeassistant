# Content platform workover (Gallery + Live Content)

**Status:** Phases 0–7 **complete** (see [CONTENT_PLATFORM_PROGRESS.md](CONTENT_PLATFORM_PROGRESS.md))  




**Repos:** [ha-digital-frames](https://github.com/dsackr/ha-digital-frames) + content catalog [frame-addons](https://github.com/dsackr/frame-addons)  
**Related:** KPF 17 (art packs), KPF 18 (widgets), KPF 20 (schedules), KPF 28 (skills / Daily Content); design note [FRAME_PORT.md](FRAME_PORT.md)

This is the publish-as-we-go plan to fix the **Add-ons / xOTD / skills / widgets** tangle. Each **phase is a shippable release** (one or more PRs that can hit `main` independently). Later phases must not be required for earlier ones to be useful.

---

## North star

Two clear product jobs:

| Surface | User job | Content type |
|---|---|---|
| **Gallery** | Find classic / seasonal art without hunting Wikimedia | Static, curated image packs → library (+ optional scene) |
| **Live** | Daily / rotating generated content on frames | Generators (joke, quote, word, scripture, photo feeds, agenda, …) → **render → FramePort send** |

**Hard rules going forward:**

1. Generators are **frame-agnostic content** + **HA schedules / Send Now / walls** — never “install binds one frame IP and a private timer.”
2. Generators **never POST to the frame themselves.** Core owns encode + send (queue-on-sleep, Meural/Samsung, thumbnails).
3. Remote “download Python from GitHub and exec” is **not** a community marketplace model. First-party renderers only until a non-exec plugin surface exists.
4. **Art catalog ≠ app store.** Gallery language for images; Live for functionality.

---

## Current state (baseline to leave)

```
Panel:  Dashboard | Add-ons | Daily Content
        ├── Art packs (scene_packs)     → ScenePackManager install → library + scene
        ├── Productivity “widgets”      → ScenePackManager widget path → subprocess + frame IP
        └── Skills (xOTD migration)     → SkillManager → pinned xotd_renderer --render-only → core send

Catalog (frame-addons): scene_packs/index.json mixes art + daily_agenda + vestigial xotd widget
```

Pain: dual schedulers, dual send paths, jargon (add-on / widget / skill / xOTD / scene pack), Agenda outside FramePort, half-migrated xOTD.

---

## Phase map (publish order)

| Phase | Name | Ships to user as | Depends on | Risk |
|:---:|---|---|---|---|
| **0** | Contract + rename map | Docs only (this file + KPF notes) | — | None |
| **1** | Surface rename + jargon purge | Clearer tabs/copy; same behavior | 0 | Low |
| **2** | Gallery install UX | Better art install choices | 1 | Low |
| **3** | Live quick-setup | One dialog: content → frame(s) → time | 1 | Medium |
| **4** | Agenda as Live generator | Agenda uses skills + schedules + core send | 3 recommended | High |
| **5** | Retire widget runtime | No private widget scheduler / frame-IP scripts | 4 | Medium |
| **6** | Catalog split + branding | Art-only index; generators first-party | 5 | Low |
| **7** | Marketplace foundations | Versioned art catalog; no remote-exec community code | 6 | Product |

Phases **1–3** can land while Agenda still uses the old widget path. Phase **4–5** are the architecture cutover. **6–7** polish and future marketplace.

---

## Phase 0 — Contract lock (docs only)

**Goal:** Shared vocabulary and non-goals so implementers don’t re-introduce widgets.

### Deliverables

- This roadmap (checked into `docs/`).
- Short “naming map” in KPF 17 / 18 / 28 headers (amend when code lands; Phase 0 only cross-links).

### Vocabulary (use these words in UI + new code)

| Prefer | Avoid for user-facing |
|---|---|
| Gallery | Add-ons (for art) |
| Art pack / collection | Scene pack (OK in code until rename) |
| Live content / Daily | xOTD, “skill” as primary noun |
| Setup / routine | Widget instance |
| Generator (eng) | Widget (eng) |

### Non-goals for Phases 1–5

- Multi-publisher marketplace UI  
- Community-submitted Python renderers  
- Rewriting art pack image pipelines  
- Full panel rewrite / framework migration  

### Ship criteria

- [x] Roadmap merged on `main` (or present in working tree / shipped with Phase 1)  
- [x] No new widget packs while Phases 4–5 are open (documented in frame-addons README)  

---

## Phase 1 — Surface rename + jargon purge (publishable UX)

**Goal:** Users understand the two jobs without behavioral change.

### User-visible

| Before | After |
|---|---|
| Tab **Add-ons** | **Gallery** |
| Tab **Daily Content** | **Live** (subtitle: daily jokes, quotes, photos…) |
| Section “Art Packs” | keep or “Collections” |
| Section “Productivity Packs” | **Live add-ons** (temporary) or hide Agenda behind Live once Phase 4 ships; until then: **Tools** with one card “Daily Agenda (legacy)” |
| Skill blurb with “skill is a piece of content…” | Plain language: “Reusable daily content. Schedule it or send it like a photo.” |
| flow / empty states mentioning xOTD | Digital Frames / Live |

### Technical (ha-digital-frames)

- [ ] `digital-frames-panel.js`: tab ids can stay (`addons`, `xotd`) internally **or** rename carefully with Playwright updates — prefer **labels first**, ids in a follow-up micro-PR if risky.
- [ ] strings/help text in panel + card Daily picker.
- [ ] README / INSTALLATION / frame-addons README: Gallery vs Live; note xOTD is internal renderer name only.
- [ ] Remove **catalog listing** of pack id `xotd` from `frame-addons` `index.json` (panel already hides it; delete the entry so nothing re-surfaces). Keep `addons/xotd/` tree for the pinned renderer.

### Tests / KPF

- Amend **KPF 17** description (Gallery naming).  
- Amend **KPF 28** (Live tab naming).  
- Update Playwright: `addons-categories.spec.js`, `addons-catalog-refresh.spec.js`, `skills.spec.js` selectors/labels.  
- No new backend tests required if pure copy/label.

### Ship criteria

- [x] Tabs read Gallery / Live on a fresh install  
- [x] No user-facing “xOTD” or “Add-ons” for art (tab labels; catalog drops xotd pack)  
- [ ] Panel suite green (run before merge)  
- [x] Can ship on `main` without migrating any stored data  

### Out of scope

Agenda architecture, skill API changes, catalog structure.

**Implemented:** panel labels/copy, Tools section, frame-addons index + README. Internal tab ids still `addons`/`xotd`.

---

## Phase 2 — Gallery install UX (art marketplace that feels like art)

**Goal:** Installing famous art matches the intent “I want Monet on my frames,” not “I installed a scene pack add-on.”

### User-visible

1. Pack detail: title, description, **image count**, license line, cover + scrollable titles (already partial).
2. Install actions (pick one primary + overflow):
   - **Add to library** (album = pack name) — always.
   - **Add + create scene** — current default behavior; make explicit.
   - Optional later in same phase if cheap: **Send one random piece now** (needs frame picker).
3. After install: toast with links — “View in library” / “Open scene” (deep-link tab + filter if easy).
4. Installed state: clear **Update / Sync / Remove** copy (not “uninstall add-on”).

### Technical

- [ ] Panel install modal / confirm step (may be new UI over existing `POST …/scene_packs/…` APIs).
- [ ] Prefer **no API break**: install still uploads via `LibraryManager` + optional scene.
- [ ] If “library only” needs a flag: `async_install_pack(..., create_scene: bool = True)`.
- [ ] KPF 17 entry points + tests for `create_scene=False` path.

### Tests / KPF

- Backend: install without scene still tracks image_ids / album.  
- Panel: install CTA labels; category tiles still work.  
- Amend **KPF 17**.

### Ship criteria

- [x] User can install Monet as library-only without a scene  
- [x] Default path still creates scene (no surprise for existing users)  
- [x] Publish independently of Live work  

**Implemented:** `create_scene` on install API + dual CTAs on Gallery cards.

---

## Phase 3 — Live quick-setup (80% path)

**Goal:** “Joke of the Day on the kitchen frame every morning” without three tabs.

### User-visible

**Live** tab layout:

1. **Quick setups** (built-ins): Word / Joke / Quote / Scripture / Photo of the Day (feeds) — each tile opens a short wizard:
   - Target frame(s) (multi-select OK)
   - Time (daily) or “only on demand”
   - Optional theme/options collapsed under Advanced
2. **Your setups** — list of schedules that fire Live content (and free-standing skills with no schedule).
3. **Advanced: manage content presets** — current skill CRUD (renamed).

Card / wall skill pickers: keep working; rename “Skills” → “Live content” in pickers.

### Technical

- [ ] New thin API **or** panel composition of existing APIs:
  - Ensure skill exists (builtin id or create)
  - `ScheduleManager.async_create_schedule` with action `{ type: skill, skill_id }` per frame **or** one schedule with multi-target if supported — **audit schedules model first**; if one frame per schedule, create N schedules from the wizard.
- [ ] Prefer **no second scheduler**.
- [ ] Builtin skills already seeded in `SkillManager` — wizard should **reuse** `word_of_the_day` etc., not duplicate.
- [ ] Idempotent: second quick-setup for same builtin+frame updates schedule, doesn’t clone skills forever.

### Tests / KPF

- Backend: helper or HTTP endpoint tests for “setup live routine.”  
- Panel: `skills.spec.js` + new quick-setup flow.  
- Amend **KPF 28** + **KPF 20** (schedules created from Live).  
- New KPF only if the wizard is a distinct flow number; else amend 28.

### Ship criteria

- [x] New user can complete joke→frame→08:00 without opening Schedules tab  
- [x] Resulting fire path is normal schedule → skill render → core send  
- [x] Advanced skill editor still available  
- [x] Publish while Agenda is still a Gallery “Tools” card (legacy)  

**Implemented:** `POST /api/digital_frames/live/quick_setup`; Live card “Schedule daily” + time. Multi-frame: pass multiple `entry_ids` (one schedule each). UI currently one frame per card select.

### Risks

- Schedules multi-frame semantics — document chosen model in PR.  
- Don’t break wall skill mappings.

---

## Phase 4 — Agenda as Live generator (architecture pivot)

**Goal:** Daily Agenda is a first-class Live preset: same mental model and send path as Joke of the Day.

### User-visible

- Agenda appears under **Live** (quick setup + config: calendars, weather).
- Removed from Gallery / productivity pack install (or install becomes “enable generator” with no frame IP).
- Works on **Fraimic + Meural** (JPEG via existing text/image skill payload patterns). Samsung only if FramePort send already works for that driver.

### Technical design

1. **New skill `content_mode`: `agenda`** (or `dashboard_agenda`).
2. Config: calendar source (HA entities / iCal), weather prefs — reuse schema ideas from current widget `config_schema`.
3. Render path:
   - Port `agenda_renderer.py` to **`--render-only`** contract (mirror xOTD): write preview PNG + Spectra bin (or RGB only + core encodes) under a temp dir; **no frame HTTP client in the happy path**.
   - `SkillManager._async_render_*` dispatches agenda like text modes.
   - Pin script URL/SHA in `const.py` (same pattern as `XOTD_RENDERER_*`) **or** vendor a slimmed renderer into the integration later (Phase 6 decision).
4. **Migration** on setup load:
   - Detect installed widget `daily_agenda` in scene_packs store.
   - Create skill + schedule(s) from widget config + `frame_id`.
   - Uninstall widget install record; cancel `_schedule_widget`.
   - One-shot flag in storage so migration doesn’t re-run.
5. Keep old widget path **read-only fallback for one release** if migration fails (log + repair note); delete in Phase 5.

### Tests / KPF

- Backend: agenda render mock subprocess; migration test (like `test_xotd_migration.py`).  
- Panel: agenda config fields under Live (reuse schema engine).  
- **KPF 18** rewritten → “Live generators: agenda” or merge into **KPF 28** and mark 18 superseded.  
- Close widget execution **Gap** by testing the new path instead.

### Ship criteria

- [ ] Fresh install: Agenda only via Live  
- [ ] Upgraded install: existing Agenda users keep a daily fire without reconfigure (migration)  
- [ ] Send goes through coordinator / queue-on-sleep  
- [ ] Meural receives JPEG, not Spectra bin  

### Out of scope

Community agenda variants; full layout redesign.

---

## Phase 5 — Retire widget runtime

**Goal:** One dynamic-content architecture. Delete the foot-gun.

### Technical

- [ ] Remove from `ScenePackManager`: `_async_install_widget`, `_schedule_widget`, `async_run_widget`, widget branch in uninstall, calendar pre-fetch-for-subprocess special cases that only exist for widgets.
- [ ] `scene_packs_http.py`: reject `type==widget` installs with clear error (or ignore catalog widgets).
- [ ] Panel: remove widget install modal path; schema engine may remain for Live advanced forms.
- [ ] `frame-addons` index: no `type: widget` entries.
- [ ] Docs: KPF 18 → retired / redirected; TESTING_STRATEGY widget gap closed.
- [ ] Optional: fail loud if leftover `digital_frames_addons/daily_agenda` dirs exist (log warning + repair skill).

### Ship criteria

- [ ] Grep clean: no `_schedule_widget` / `async_run_widget`  
- [ ] Catalog has zero widgets  
- [ ] Suite green; no user path creates widget installs  

**Depends on Phase 4** (Agenda must not need widgets).

---

## Phase 6 — Catalog split + branding (content repo hygiene)

**Goal:** Catalog shape matches product; branding is Digital Frames.

### frame-addons repo

| Path | Role |
|---|---|
| `art/index.json` (or keep `scene_packs/index.json` art-only) | Image packs only |
| `addons/xotd/` | Renderer asset for pinned SHA (not catalogued) |
| `addons/daily_agenda/` | Renderer asset for pinned SHA until vendored |
| README | Digital Frames Gallery + Live renderers; not “Fraimic add-ons marketplace” |

### ha-digital-frames

- [ ] `SCENE_PACK_INDEX_URL` points at art-only index (compat: accept old URL one release if needed).
- [ ] Generator pins stay in `const.py`.
- [ ] Consider renaming `ScenePackManager` → `ArtPackManager` (behavior-preserving refactor PR, separate from UX).
- [ ] `ADDONS_DIRNAME` temp dirs for skill runs OK; don’t imply user-facing “add-ons.”

### Ship criteria

- [ ] Gallery fetch does not parse widgets  
- [ ] Docs/CONTRIBUTING match  
- [ ] Publish can be same week as Phase 5 or immediately after  

---

## Phase 7 — Marketplace foundations ✅

### Shipped

1. **Versioned art manifests** — `schema_version`, pack `version` /
   `min_integration` / `featured` via `frame-addons/scripts/stamp_catalog.py`
   and `docs/CATALOG_SCHEMA.md`.  
2. **Checksummed packs** — per-image `sha256` verified on install (integrity).  
3. **Search + featured** — Gallery search box + Featured strip + category browse.  
4. **Community art PR template** — `.github/PULL_REQUEST_TEMPLATE/art_pack.md`
   (images/JSON only; public-domain checklist).  
5. **No community remote-exec** — widgets filtered; generators stay pinned Live skills.

### Explicitly out of scope forever (unless redesign)

- “Install this random Python from the internet onto HA and let it talk to your frame.”

---

## Cross-cutting concerns (every phase)

### FramePort

Any generator work must call the same send path as library/skills today (`async_send_image_or_queue` / scene mappings). No new direct `aiohttp` to frame IP from feature code.

### Multi-driver

| Driver | Phase 3 | Phase 4 Agenda |
|---|---|---|
| Fraimic Spectra | required | required |
| Meural | already OK for text skills | required (JPEG) |
| Samsung experimental | best-effort | best-effort |

### Migration philosophy

- Prefer **one-shot silent migration** with log line + optional notification.  
- Never leave users with **two** Agenda systems armed.  
- Store flags under `digital_frames_*` keys, not new domains.

### Testing bar (AGENTS.md)

Every user-facing phase ships with:

1. KPF amend (or new stable number — never renumber).  
2. pytest and/or Playwright that match Test status.  
3. No “fix tests next PR” for the phase’s own behavior.

### Release notes template (each phase)

```markdown
## Digital Frames x.y.z — Content platform Phase N
### For users
- …
### For existing installs
- Migration: … / none
### For contributors
- frame-addons: …
```

---

## Suggested PR slicing (how to “publish as we go”)

| Ship | PR(s) | Notes |
|---|---|---|
| Phase 0 | `docs: content platform roadmap` | This file |
| Phase 1a | Panel labels + empty-state copy | Fastest user win |
| Phase 1b | frame-addons: drop xotd catalog entry + README | Coord same week |
| Phase 2 | Art install options + backend flag | |
| Phase 3a | Backend “ensure skill + create schedule” helper | |
| Phase 3b | Live quick-setup UI | |
| Phase 4a | Agenda `--render-only` in frame-addons | Can merge first |
| Phase 4b | `content_mode=agenda` + send path | |
| Phase 4c | Widget → skill/schedule migration | |
| Phase 4d | Live UI for Agenda config | |
| Phase 5 | Delete widget runtime + catalog | After 4c soaked |
| Phase 6 | Index split + renames | Quiet refactor OK |
| Phase 7 | Separate initiative | Don’t block 1–6 |

**Soak recommendation:** After Phase 4c, wait **one release** (or ~1 week production) before Phase 5 delete, so migration bugs can be fixed while fallback exists.

---

## Success metrics (informal)

| Signal | Before | After Phase 5+ |
|---|---|---|
| “How do I get Monet?” | Add-ons → categories → install pack | Gallery → Famous artists → Monet |
| “Joke every morning” | Daily Content skill + Schedules tab | Live → Joke → frame → time |
| “Agenda” | Productivity pack, frame-bound widget | Live generator, FramePort send |
| Schedulers for dynamic content | Schedules **and** widget timers | Schedules only |
| Remote exec for product features | Widget + skill renderers | First-party pinned render-only only |

---

## Open decisions (resolve at phase start, not mid-PR)

1. **Tab internal ids** — rename `addons`/`xotd` DOM ids in Phase 1 or label-only?  
   - Recommendation: **labels in 1a**, id rename in 1b with Playwright.  
2. **Agenda renderer location** — stay in frame-addons (pinned) vs vendor into integration?  
   - Recommendation: pinned through Phase 4–5; revisit vendoring in Phase 6 if pin thrash is painful.  
3. **Schedule model for multi-frame quick-setup** — N schedules vs multi-target action?  
   - Recommendation: N schedules if simpler and already tested; multi-target only if schedules already support it.  
4. **Gallery-only install default** — create scene still default?  
   - Recommendation: **yes** (compat); library-only is opt-in checkbox.

---

## Appendix A — Code anchors (today)

| Area | Primary files |
|---|---|
| Art + widget manager | `custom_components/digital_frames/scene_packs.py`, `scene_packs_http.py` |
| Skills / Live | `skills.py`, `skills_http.py` |
| Schedules | `schedules.py`, `schedules_http.py` |
| Panel tabs | `digital-frames-panel.js` (tab bar ~2327+, Gallery ~2431+, Live ~2442+, packs ~8587+) |
| Pins / catalog URLs | `const.py` (`SCENE_PACK_*`, `XOTD_RENDERER_*`, `ADDONS_DIRNAME`) |
| xOTD migration precedent | `__init__.py` `_async_migrate_xotd_instances`, `tests/python/setup/test_xotd_migration.py` |
| Catalog | `../frame-addons/scene_packs/index.json`, `addons/xotd/`, `addons/daily_agenda/` |

## Appendix B — Phase checklist (copy into PR description)

```
Phase: _
User-visible:
- 
Migration:
- none | …
KPF:
- amended: …
Tests:
- pytest: …
- playwright: …
frame-addons change needed: yes/no
Follow-ups deferred:
- 
```
