# FramePort design note

**Status:** Phase 0 design + **Phase 1 codec seam** + **Phase 2
codec-keyed library cache** landed. Full FramePort ABC / second driver
still open.  
**Purpose:** freeze the contract that lets the gallery core (library, walls,
scenes, schedules, skills, panel) treat every display the same way, while
each hardware family keeps its own transport, pixel format, and discovery.

This is the multi-frame product direction note. It is not a rename plan and
not a Meural implementation plan.

Related:

- [KEY_PRODUCT_FLOWS.md](KEY_PRODUCT_FLOWS.md) — user-facing flows and tests
- [CONTRIBUTING.md](../CONTRIBUTING.md) — current module layout
- [`frame_types.py`](../custom_components/fraimic/frame_types.py) — panel
  profiles for the Fraimic protocol family only

---

## 1. Problem this solves

Today the product UX is already mostly vendor-agnostic (walls, scenes,
library, schedules, skills). The **send path is not**:

| Concern | Today | Problem for non-Fraimic hardware |
|--------|--------|-----------------------------------|
| Frame identity | HA config `entry_id` for domain `fraimic` | Fine if every frame is still an entry; wrong if we only key on Fraimic-shaped data |
| “How to compose” | `helpers.render_spec_for_entry` → `RenderSpec` | Geometry/orientation is universal; Spectra assumptions creep in later |
| Wire payload | Library `async_get_bin_for_send` → Spectra `.bin` | Library pre-assumes Spectra 6 packing |
| Delivery | `FraimicCoordinator.async_send_image_or_queue` | Queue-if-asleep, `/api/info`, `.bin` POST are Fraimic-protocol-specific |
| Panel catalog | `FRAME_TYPES` (size, resolution, byte layout, official/clone) | Collapses **codec** and **marketing origin** into one table; understates real send-pipeline differences (see §1.1) |

### 1.1 Three layers (not two)

The first draft of this note treated “official vs clone” as the main split.
That is too coarse. In particular the **7.3" community panel is not “just a
clone of Fraimic”** in the sense of identical image bytes on the wire — it
already needs a **different way to turn a photo into a payload**, even when
it reuses a Fraimic-*shaped* HTTP API.

Use three layers:

```text
┌─────────────────────────────────────────────────────────────┐
│  Core — gallery product                                     │
│  library · walls · scenes · schedules · skills · panel      │
└────────────────────────────┬────────────────────────────────┘
                             │ FramePort (capabilities + send)
┌────────────────────────────▼────────────────────────────────┐
│  Driver / transport — how HA talks to the device             │
│  e.g. local POST /api/image + /api/info · Meural cloud API  │
└────────────────────────────┬────────────────────────────────┘
                             │ PanelCodec (encode for this panel)
┌────────────────────────────▼────────────────────────────────┐
│  Codec / panel profile — how pixels become wire bytes       │
│  e.g. Spectra6 split-half · Spectra6 sequential · JPEG      │
└─────────────────────────────────────────────────────────────┘
```

| Layer | Owns | Examples in this repo today |
|-------|------|-----------------------------|
| **Core** | Identity, library, walls, scenes, who gets which image | `walls.py`, `scenes.py`, panel |
| **Driver / transport** | Probe, poll, HTTP/cloud auth, deliver bytes, sleep-queue policy | `coordinator.py`, `helpers.probe_frame`, `const.API_*` |
| **Codec / panel profile** | Resolution, palette packing, byte layout, cache format id | `frame_types.py` + `image_converter.py` |

**Same driver, different codec** is already real:

| Panel | Origin label today | Codec | Transport (as implemented) |
|-------|--------------------|-------|----------------------------|
| Fraimic 13.3" / 31.5" | official | Spectra 6 **split-half** (EL133UF1-style) | `POST /api/image` octet-stream |
| 13.1" community | clone | Spectra 6 **split-half** (same pack as 13.3") | same HTTP shape |
| **7.3" ESP32-C6** | clone (misleading) | Spectra 6 **sequential** (Waveshare E6 / `epd7in3e`-style) | same endpoint in code, **different payload**, plus ESP32 redraw/timeout semantics |

So: 7.3" is **not** a separate product integration and **not** Meural-class
foreign hardware — but it **is** a second **PanelCodec** under the local
Spectra HTTP driver. Calling it only “clone” hid the fact that send-path
correctness already branches on packing (`LAYOUT_SEQUENTIAL` vs
`LAYOUT_SPLIT_HALF`), discovery quirks (`detect_frame_type_from_info`),
and delivery timeouts (240s upload, queue-vs-unconfirmed timeout handling
in the coordinator).

**Meural** still needs a **second driver** (different transport + usually a
JPEG/rgb codec). It must not become another row that only sets resolution
in `FRAME_TYPES`.

**Implication for Phase 1:** extract **codec + transport policy** as explicit
seams *inside* today’s stack (7.3" is the forced example), not only a
vague “FramePort wrapper around the whole coordinator.” Meural can wait
until that seam is real.

---

## 2. What a “frame” is to the core

To library / walls / scenes / schedules / panel, a frame is only:

| Field | Meaning |
|-------|---------|
| `frame_id` | Stable string identity. **v1 = config entry `entry_id`** (same as today for walls/scenes/schedules). |
| `name` | User-facing label |
| `width` / `height` | Native panel pixels (buffer orientation as reported/stored) |
| `online` | Last-known reachability for UI / send feedback |
| `driver` | Which FramePort implementation owns this frame (e.g. `fraimic`) |
| `capabilities` | See §3 |

Everything else (host, MAC, device key, cloud tokens, Spectra layout,
battery) is **driver-private** and must not be required by core paths.

### Identity rule (v1)

- Walls (`walls.py` placements), scenes (`scenes.py` mappings), and
  schedules continue to key on **`entry_id`**.
- Removing a frame prunes that id from walls (existing
  `WallManager.async_prune_entry`).
- Re-adding the same physical device may yield a new `entry_id` (already
  true today); no change to that contract in Phase 1.
- Future drivers that are not HA config entries of this integration would
  need a stable id scheme; **out of scope until a second driver exists**.
  Prefer: every frame still has a config entry (or hub entry + device id)
  so core keeps one id space.

---

## 3. Capability flags (v1)

Capabilities are how the panel and services degrade without lying about
hardware. Core must branch on flags, not on `driver == "fraimic"`.

| Capability | Type | Meaning |
|------------|------|---------|
| `color_mode` | enum | `spectra6` \| `rgb` \| `grayscale` (extensible) |
| `preferred_payload` | enum | High-level family: `spectra6_bin` \| `jpeg` \| `png` (wire container after encode) |
| `codec_id` | str | Concrete encoder id used in cache keys, e.g. `spectra6_split_half`, `spectra6_sequential`, `jpeg_q90` |
| `sleep_queue` | bool | Unreachable/asleep frames may queue a send for later delivery (KPF 4) |
| `battery` | bool | Expose battery / charging sensors |
| `orientation_lock` | bool | User may pin portrait/landscape + hanging edge + 180° flips (KPF 2/22) |
| `local_only` | bool | No cloud required for normal send/poll |
| `commands` | frozenset | Subset of `restart`, `sleep`, `refresh` (HA services / device actions) |
| `max_payload_bytes` | int \| None | Optional size limit for uploads |
| `send_timeout_s` | int \| None | Optional transport timeout (7.3"/ESP32 needs a long budget today) |

**v1 local Spectra HTTP driver** — shared transport, **per-panel codec**:

```text
# Official 13.3" / 31.5" (and 13.1" community with same pack)
color_mode=spectra6
preferred_payload=spectra6_bin
codec_id=spectra6_split_half
sleep_queue=True
battery=True            # override per entry if a build has none
orientation_lock=True
local_only=True
commands={restart, sleep, refresh}

# 7.3" ESP32-C6 community panel — same driver family, different codec + timing
color_mode=spectra6
preferred_payload=spectra6_bin
codec_id=spectra6_sequential
sleep_queue=True
battery=…               # device-dependent
orientation_lock=True
local_only=True
commands={restart, sleep, refresh}
send_timeout_s=240      # blocks on e-ink redraw before HTTP response
```

**Illustrative Meural-shaped profile** (not implementing yet — for sizing the port):

```text
color_mode=rgb
preferred_payload=jpeg
codec_id=jpeg_q90       # or whatever the API accepts
sleep_queue=False       # or different retry policy under that driver
battery=False
orientation_lock=…      # only if the API supports it
local_only=False        # if cloud auth is required
commands=…              # whatever the API exposes
```

Panel rule of thumb: show the same shells (frame on wall, send, scene
participation); hide or disable controls whose capabilities are false.

---

## 4. Who owns conversion

**Rule (non-negotiable for multi-driver):**

1. **Library** stores **originals** (and crop metadata, albums, tags, voice
   names). That is the canonical product asset store.
2. **Core** decides *which* image (and crop / skill render intent) goes to
   *which* `frame_id`, using `RenderSpec`-equivalent geometry.
3. **Driver + codec** turn that intent into a **wire payload**: the codec
   encodes pixels; the transport delivers and applies sleep-queue /
   timeout policy. Cache keys include `codec_id` (not only resolution).

### Today’s reality (already multi-codec under one HTTP stack)

- Cache path is Spectra-shaped: resolution + `RenderSpec.variant` → `.bin`
  (`library.py` `_bin_path` / `async_get_bin_for_send`).
- Layout is chosen via `frame_types.byte_layout_for_resolution` — this is
  the **hidden codec branch** (split-half vs sequential for 7.3").
- `_validate_registry` exists because two panels at the same resolution
  with different layouts would corrupt a resolution-only cache — proof
  that **codec_id belongs in the cache key**.
- Scene fan-out (`SceneManager.async_send_mappings`) **prepares bins first**,
  then calls `coordinator.async_send_image_or_queue` — two-phase “resolve
  then send”; prepare step is codec-specific, deliver step is transport.

### Target split

```text
Core / library
  async_get_source_for_send(image_id, crop?) -> original bytes + meta
  render_spec_for_frame(frame) -> geometry (width, height, rotation, locked)

Driver (transport + selected codec for this entry)
  codec.encode(source, render_spec, crop?) -> WirePayload   # PanelCodec
  transport.deliver(payload, policy) -> SendResult          # sleep queue, timeouts
```

Optional shared helpers (not owned by any one cloud/vendor):

- Pillow decode, cover-crop, manual crop, canvas rotation — already mostly
  in `image_converter.py` / crop paths; keep as **shared render toolkit**.
- Spectra nibble packing (split-half **and** sequential) — **local Spectra
  driver codecs**, not core. Prefer named codecs over a single
  “if 7.3 then …” branch scattered through library code.

### Cache key direction

Today (simplified — layout only implicit via resolution uniqueness):

```text
(image_id, width, height, variant) -> .bin
```

Target:

```text
(image_id, crop_id?, width, height, rotation/locked variant, codec_id)
  -> opaque payload bytes
```

`codec_id` examples: `spectra6_split_half`, `spectra6_sequential`,
`jpeg_q90`. Library may host the blob store API, but **must not assume**
the blob is Spectra `.bin` or that resolution alone selects packing.

Until Phase 2 lands, the local Spectra path may keep calling
`async_get_bin_for_send` **from the driver/codec boundary** so behavior
stays identical — but Phase 1 should make that call site obvious (one
module), not scattered.

---

## 5. FramePort methods (v1 sketch)

Names are illustrative; Phase 1 may wrap existing classes rather than
introduce a formal ABC on day one. Semantics matter more than the type
hierarchy.

```text
FramePort / FrameHandle
───────────────────────
frame_id: str
name: str
capabilities: Capabilities
native_size: (width, height)

async def async_get_status() -> FrameStatus
  # online, optional battery/wifi/firmware, driver-private extras

async def async_send(
    source: ImageSource,          # library image_id | raw bytes | skill result
    *,
    render_spec: RenderSpec,      # or resolved by driver from entry options
    crop: CropSpec | None = None,
    preview_hint: bytes | None = None,
) -> SendResult
  # SendResult: success, queued?, unconfirmed?, message?
  # If capabilities.sleep_queue: may return queued=True instead of failing hard

# Optional — only if listed in capabilities.commands
async def async_command(name: str) -> None
```

### Mapping onto today’s Fraimic stack

| Port concept | Current entry point |
|--------------|---------------------|
| Status / poll | `FraimicCoordinator._async_update_data`, sensors |
| Transport deliver + sleep queue | `FraimicCoordinator.async_send_image_or_queue` → `async_send_image` |
| Geometry | `helpers.render_spec_for_entry` |
| Codec encode | `image_converter.convert_image*` + `frame_types.byte_layout` (split-half vs sequential) |
| Multi-frame fan-out | `SceneManager.async_send_mappings` (must stay the single multi-send executor) |
| Panel catalog | `FRAME_TYPES` — **local Spectra driver panel profiles** (should evolve toward codec_id + transport hints, not only “official/clone”) |
| Discovery / add | `config_flow.py`, `helpers.probe_frame`, `discovery.py` — **driver** |

Phase 1 success condition:

1. **Every send path** reaches the device only through a single local-Spectra
   FramePort façade (or clearly named equivalent).
2. **Encode is an explicit PanelCodec step** (at least: split-half vs
   sequential selected by panel profile / `codec_id`), not an incidental
   side effect of resolution → layout lookup buried in library backfill.
3. **7.3" and 13.3" both work unchanged** on hardware / existing tests —
   they prove multi-codec under one driver without Meural.

---

## 6. Core vs driver: KPF map

Legend:

- **Core** — gallery product; must not import Fraimic wire protocol details
- **Driver (Fraimic)** — protocol, Spectra, discovery for this family
- **Shared toolkit** — pure image math usable by any driver
- **Mixed** — stays core orchestration, driver for the last mile

| KPF | Title (short) | Layer | Notes |
|-----|---------------|-------|--------|
| 1 | Discovery & add-frame wizard | **Driver** | Each driver owns its config flow / probe |
| 2 | Options (scan interval, size, orientation edge, 180°) | **Mixed** | Orientation/edge → core `RenderSpec` if `orientation_lock`; size catalog is driver |
| 3 | Coordinator polling & IP self-heal | **Driver** | LAN/DHCP behavior is Fraimic-shaped |
| 4 | Send image / queue-if-asleep | **Driver** (policy) + **Core** (call site) | Core always calls port `async_send`; queue is capability-gated inside driver |
| 5 | HA services | **Core** façade, **Driver** for commands/send | Service names may stay `fraimic.*` until a later branding phase |
| 6 | Voice/AI intents | **Core** | Resolves frame by name → `frame_id` → port send |
| 7 | Spectra image conversion | **Driver / codec** | Not a core primitive |
| 8 | Shared image library | **Core** | Originals, thumbs, tags, voice names |
| 9 | Library storage backends | **Core** | Local / Dropbox / Drive |
| 10 | Library discovery (Dropbox inbox) | **Core** | |
| 11–12 | Crop editor / crops | **Core** (+ shared toolkit) | Crops are product state, not Spectra-specific |
| 13–14 | Scenes CRUD + send | **Core** | Mappings are `frame_id → image/skill`; prepare/send via port |
| 15 | Scene packs / art packs | **Core** | Install into library + auto scene |
| 16–17 | Walls | **Core** | Placements by `frame_id` |
| 18–20 | Schedules / skills / xOTD (as applicable) | **Core** orchestration | Skill pixel output still needs driver render for Spectra; skill may produce RGB intermediate |
| 21 | Sensors / orientation select / camera | **Mixed** | Sensors mostly driver; orientation select is core option if capability allows |
| 22 | Render spec | **Core** (geometry) | Keep independent of Spectra packing |
| 23 | Frame-type registry | **Driver panel profiles / codecs** | Resolutions + **codec** (layout); “clone” origin is secondary metadata |
| 24–25 | Onboarding / domain setup | **Core** shell | Driver registration plugs into setup |
| 26–30 | Panel UX, card, media source, etc. | **Core** | Capability-gated chrome; no Spectra knowledge in JS |

When a future KPF is added: if it only makes sense for one wire protocol,
document it as driver-scoped. If users should get it on every frame type,
it belongs in core and must use the port.

---

## 7. Non-goals (v1 / Phase 0–1)

| Non-goal | Why |
|----------|-----|
| Repo or HA domain rename (`fraimic` → `smart_art`) | Packaging/migration cost; zero multi-driver value; display name can change later without domain change |
| Implementing Meural (or any second driver) | Premature until the seam exists and Fraimic still passes all KPFs |
| Expanding `FRAME_TYPES` for Meural | Wrong abstraction (Meural is a new driver, not a Spectra panel row) |
| Pretending 7.3" is “just a clone” with identical send bytes | It already needs a different codec + delivery timing; model that honestly |
| Supporting “every photo frame” | Port stays small; new drivers are explicit work |
| Unifying cloud auth models | Each driver owns credentials |
| Changing wall/scene id scheme away from `entry_id` | Not needed for Fraimic-only seam |
| Rewriting the panel for multi-brand theming | Branding phase later |
| Guaranteeing identical sensors across vendors | Capability matrix, not LCD |

---

## 8. Phased work after this note

| Phase | Goal | User-visible? |
|-------|------|----------------|
| **0** | This document (incl. three-layer model + 7.3" as multi-codec proof) | Done |
| **1 – Seam inside local Spectra stack** | Explicit PanelCodec (`panel_codec.py`); `codec_id` on `FrameType`; encode call sites via `encode_for_panel*`; send timeout from panel profile. 7.3" = `spectra6_sequential`, official = `spectra6_split_half`. | **Done** (behavior-preserving) |
| **2 – Format-agnostic render cache** | Library `.bin` cache keyed by `codec_id` (`bin/<WxH[variant]>/<codec_id>/…`); legacy resolution-only paths still read as fallback; send/backfill pass codec from entry/resolution. | **Done** |
| **3 – Second driver** | e.g. Meural experimental: add, wall, send, scene. Proves a *new transport*, not just a new codec. | Yes — next |
| **4 – Branding** | Product/panel naming (“Smart Art” or similar); optional domain migration only if still worth it | Yes |

**Immediate next implementation step:** Phase 3 — first foreign driver
(Meural or similar), using FramePort + codec-keyed cache.

**Do not start Phase 3 until Phase 1–2 stay green on pytest + Playwright
and KPF 4/7/8/22/23 hold for both official and 7.3" panels.**

---

## 9. Testing implications

- **Core** tests should eventually use a **fake FramePort** (in-memory:
  records sends, fixed geometry, configurable capabilities) so walls/scenes/
  schedules do not need a Spectra packer or HTTP frame.
- **Fraimic driver** tests keep today’s coordinator / image_converter /
  frame_types coverage.
- Panel tests stay against the mock server; when capabilities appear in
  `/api/.../frames`, mock frames should expose them so UI gating is
  testable.
- No new KPF is required for this design doc alone. Phase 1 that only
  refactors without behavior change updates entry points in existing KPFs
  if file/function names move. Phase 2–3 that change behavior ship KPF +
  tests per [AGENTS.md](../AGENTS.md).

---

## 10. Open questions (defer until Phase 1 design review)

These do **not** block accepting this note; they should be decided when
code lands:

1. **ABC vs protocol vs thin façade** — formal `FramePort` type vs
   “coordinator is the port for now.”
2. **Where payload cache lives** — still under library storage backends vs
   driver-local store.
3. **Skill renders** — always RGB intermediate then driver encode, or allow
   skills to emit driver-native bins for speed (today: some paths already
   emit `.bin`).
4. **Multiple drivers, one HACS package** vs separate integrations that
   register into one core — packaging choice for Phase 3.
5. **Product display name** while domain remains `fraimic`.

---

## 11. Acceptance for this document

This note is “done” if a reader can answer without inventing design mid-refactor:

1. **What would core call to put image X on frame Y?**  
   → Resolve `RenderSpec` / source → `FramePort.async_send(...)`.
2. **How is 7.3" different from official Fraimic?**  
   → Same local Spectra **driver/transport family** (as implemented today);
   different **PanelCodec** (`spectra6_sequential` vs `spectra6_split_half`)
   and transport timing — not “identical clone bytes,” not a Meural-class
   second integration by itself.
3. **What would a Meural driver own?**  
   → Discovery/auth, status, its **codec** (e.g. JPEG) + **transport**,
   capability flags — **not** walls/scenes/library.
4. **Where does Spectra packing live?**  
   → Local Spectra **codecs** (KPF 7/23), not as a library universal; cache
   keys include `codec_id`.
5. **What is explicitly out of scope until later?**  
   → Rename, Meural implementation, treating Meural as a `FRAME_TYPES` row,
   broad multi-vendor marketing.

---

*Last updated: 2026-07-18 — Phase 0 design (revised: three-layer model + 7.3" codec).*
