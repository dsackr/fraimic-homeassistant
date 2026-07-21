// A minimal in-memory stand-in for the Fraimic HTTP API + Home Assistant's
// own frame/entity registries, just enough for digital-frames-panel.js's init
// sequence and the Frames/Walls/Scenes flows to run against in a real
// browser. Each test gets its own instance (see createMockServer) so state
// never leaks between tests.

const path = require('path');
const http = require('http');
const fs = require('fs');

const PANEL_JS_PATH = path.join(__dirname, '..', '..', '..', 'custom_components', 'digital_frames', 'digital-frames-panel.js');
const CARD_JS_PATH = path.join(__dirname, '..', '..', '..', 'custom_components', 'digital_frames', 'digital-frames-card.js');
const HARNESS_HTML_PATH = path.join(__dirname, 'harness.html');
const CARD_HARNESS_HTML_PATH = path.join(__dirname, 'card-harness.html');
const TINY_PNG = fs.readFileSync(path.join(__dirname, 'tiny.png'));

function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function readJsonBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => resolve(body ? JSON.parse(body) : {}));
  });
}

function readFormBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const buf = Buffer.concat(chunks);
      const contentType = req.headers['content-type'] || '';
      // The panel posts plain FormData (multipart) for real "send to frame"
      // actions, and URL-encoded only from the ?packtest modal (see that
      // modal's own comment for why). Real request.post() on the Python side
      // parses both identically -- this mirrors that so tests can drive
      // either sender.
      resolve(contentType.includes('multipart/form-data')
        ? parseMultipartFields(buf)
        : Object.fromEntries(new URLSearchParams(buf.toString())));
    });
  });
}

// Minimal multipart/form-data parser -- just enough to pull simple text
// field values (entity_id, image_id, packer) out of a FormData POST body,
// plus a '[file]' marker for file parts (which carry a filename= attribute
// and a Content-Type line the text regex can't match).
function parseMultipartFields(buf) {
  const text = buf.toString('latin1');
  const result = {};
  const re = /name="([^"]+)"\r\n\r\n([\s\S]*?)\r\n--/g;
  let m;
  while ((m = re.exec(text))) {
    result[m[1]] = m[2];
  }
  const fileRe = /name="([^"]+)"; filename="/g;
  while ((m = fileRe.exec(text))) {
    result[m[1]] = '[file]';
  }
  return result;
}

// frames: [{ entry_id, title, width, height, orientation, ... }]
// scenes: [{ scene_id, name, mappings, album, source }]
// images: [{ image_id, filename, albums: [albumName, ...] }]
// albums: [{ name, count, cover_image_id }]
// walls: [{ wall_id, name, placements }]
// scenePacks: [{ id, name, categories, ... }]
// skills: [{ skill_id, name, content_mode, config }]
// onboardingComplete: the server-side first-run-wizard flag. Defaults to
// true so every non-onboarding suite loads straight to the dashboard;
// onboarding tests opt in with false.
// updateStatus: optional override for GET/POST /api/digital_frames/update*. When
// omitted, the server reports "up to date" with no banner.
function createMockServer({
  frames = [], scenes = [], images = [], albums = [], walls = [], scenePacks = [], schedules = [],
  skills = [], discoveredFlows = [],
  onboardingComplete = true, failing = false, onboardingBroken = false,
  updateStatus = null,
} = {}) {
  let sceneList = scenes.map((s) => ({ created_at: 0, album: null, source: 'user', ...s }));
  let scheduleList = schedules.map((s) => ({
    enabled: true, status: 'pending', fired_late: false,
    created_at: '2026-01-01T00:00:00', last_fired_at: null, ...s,
  }));
  let nextScheduleId = scheduleList.length + 1;
  let skillList = skills.map((s) => ({
    config: {}, created_at: 0, ...s,
  }));
  let nextSkillId = skillList.length + 1;
  const skillSendCalls = []; // { skill_id, entry_id } per /skills/:id/send POST
  const messageSendCalls = []; // request body per /messages/send POST
  // The backend guarantees the default "All Frames" wall exists with a
  // placement for every configured frame -- mirror that here unless a test
  // seeds its own default wall record.
  let wallList = walls.map((w) => ({ created_at: 0, placements: {}, kind: 'custom', ...w }));
  if (!wallList.some((w) => w.kind === 'default')) {
    const defaultPlacements = {};
    frames.forEach((f, i) => { defaultPlacements[f.entry_id] = { x: i * 160, y: 0 }; });
    wallList.unshift({
      wall_id: 'default', name: 'All Frames', kind: 'default',
      placements: defaultPlacements, excluded: [], created_at: 0,
    });
  }
  let nextWallId = wallList.length + 1;
  let nextSceneId = sceneList.length + 1;
  let libraryBackend = 'local';
  const requestLog = [];
  const sends = []; // { entity_id, image_id, packer } per /library/send POST
  const rawSends = []; // { entity_id, has_image } per /send_image POST
  const installCalls = []; // { pack_id, config } per /scene_packs/:id/install POST
  const cropSaves = []; // { image_id, width, height, crop_box } per /library/crop POST
  const cropDeletes = []; // { image_id, width, height } per /library/crop DELETE
  let updateState = {
    installed: '0.12.100',
    running: '0.12.100',
    disk: '0.12.100',
    latest: '0.12.100',
    latest_tag: 'v0.12.100',
    latest_name: 'v0.12.100',
    release_notes: '',
    release_url: 'https://example.invalid/releases',
    update_available: false,
    banner_visible: false,
    banner_dismissed_version: '',
    needs_restart: false,
    hacs: null,
    zipball_url: 'https://example.invalid/zip',
    ...(updateStatus || {}),
  };
  const updateInstalls = [];
  const updateDismisses = [];

  // --- Embedded config/options flow state machine -----------------------
  // Mirrors DigitalFramesConfigFlow: menu user → add_fraimic/add_meural →
  // pick_device → name_device → create_entry (cannot_connect error branch)
  // and DigitalFramesOptionsFlow's single init step.
  const flowSubmissions = [];   // { flow_id, body } per step POST
  const flowDeletes = [];       // flow_id per flow DELETE
  const entryDeletes = [];      // entry_id per config entry DELETE
  const activeFlows = {};       // flow_id → current step result
  let nextFlowId = 1;

  const flowSteps = {
    user: (flowId) => ({
      type: 'menu', flow_id: flowId, handler: 'digital_frames', step_id: 'user',
      menu_options: ['add_fraimic', 'add_meural'],
      description_placeholders: null,
    }),
    add_fraimic: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'digital_frames', step_id: 'add_fraimic',
      data_schema: [{ name: 'host', type: 'string', optional: true, default: '' }],
      errors: {}, description_placeholders: null, last_step: false,
    }),
    add_fraimicCannotConnect: (flowId) => ({
      ...flowSteps.add_fraimic(flowId), errors: { host: 'cannot_connect' },
    }),
    add_meural: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'digital_frames', step_id: 'add_meural',
      data_schema: [
        { name: 'host', type: 'string', required: true },
        { name: 'name', type: 'string', optional: true, default: '' },
        { name: 'width', type: 'integer', optional: true, default: 1920 },
        { name: 'height', type: 'integer', optional: true, default: 1080 },
      ],
      errors: {}, description_placeholders: null, last_step: true,
    }),
    pick_device: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'digital_frames', step_id: 'pick_device',
      data_schema: [{
        name: 'device', type: 'select', required: true,
        options: [
          ['192.168.1.31', '192.168.1.31 — firmware 1.9.2'],
          ['192.168.1.35', '192.168.1.35 — firmware 2.0.1'],
          ['__manual__', 'Enter an IP address manually…'],
        ],
      }],
      errors: {}, description_placeholders: null, last_step: false,
    }),
    manual: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'digital_frames', step_id: 'manual',
      data_schema: [{ name: 'host', type: 'string', required: true }],
      errors: {}, description_placeholders: null, last_step: false,
    }),
    name_device: (flowId, host) => ({
      type: 'form', flow_id: flowId, handler: 'digital_frames', step_id: 'name_device',
      data_schema: [{ name: 'name', type: 'string', required: true }],
      errors: {}, description_placeholders: { host }, last_step: true,
    }),
    optionsInit: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'entry_1', step_id: 'init',
      data_schema: [
        { name: 'scan_interval', type: 'integer', valueMin: 30, optional: true, default: 300 },
        { name: 'rotation_edge', type: 'select', optional: true, default: 'left', options: [['left', 'Left edge up (Fraimic default)'], ['right', 'Right edge up']] },
        { name: 'rotate_portrait_180', type: 'boolean', optional: true, default: false },
        { name: 'rotate_landscape_180', type: 'boolean', optional: true, default: false },
      ],
      errors: {}, description_placeholders: null, last_step: true,
    }),
  };

  // Discovered flows (banner tests): pre-seeded pending flows parked on
  // name_device, resumable via GET like the real API.
  for (const d of discoveredFlows) {
    activeFlows[d.flow_id] = flowSteps.name_device(d.flow_id, d.host || '192.168.1.31');
  }

  function advanceConfigFlow(flowId, body) {
    const current = activeFlows[flowId];
    if (!current) return null;
    if (current.step_id === 'user' && current.type === 'menu') {
      if (body.next_step_id === 'add_meural') return flowSteps.add_meural(flowId);
      return flowSteps.add_fraimic(flowId);
    }
    if (current.step_id === 'add_fraimic') {
      if (body.host === '') return flowSteps.pick_device(flowId);
      if (body.host === '10.0.0.99') return flowSteps.add_fraimicCannotConnect(flowId);
      return flowSteps.name_device(flowId, body.host);
    }
    if (current.step_id === 'add_meural') {
      if (body.host === '10.0.0.99') {
        return { ...flowSteps.add_meural(flowId), errors: { host: 'cannot_connect' } };
      }
      return { type: 'create_entry', flow_id: flowId, title: body.name || 'Meural', version: 1 };
    }
    if (current.step_id === 'pick_device') {
      if (body.device === '__manual__') return flowSteps.manual(flowId);
      return flowSteps.name_device(flowId, body.device);
    }
    if (current.step_id === 'manual') {
      if (body.host === '10.0.0.99') {
        return { ...flowSteps.manual(flowId), errors: { host: 'cannot_connect' } };
      }
      return flowSteps.name_device(flowId, body.host);
    }
    if (current.step_id === 'name_device' || current.step_id === 'init') {
      return { type: 'create_entry', flow_id: flowId, title: body.name || '', version: 1 };
    }
    return null;
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const p = url.pathname;
    requestLog.push(`${req.method} ${p}${url.search}`);

    if (p === '/digital-frames-panel.js') {
      res.writeHead(200, { 'Content-Type': 'application/javascript' });
      fs.createReadStream(PANEL_JS_PATH).pipe(res);
      return;
    }
    if (p === '/digital-frames-card.js') {
      res.writeHead(200, { 'Content-Type': 'application/javascript' });
      fs.createReadStream(CARD_JS_PATH).pipe(res);
      return;
    }
    if (p === '/' || p === '/harness.html') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      fs.createReadStream(HARNESS_HTML_PATH).pipe(res);
      return;
    }
    if (p === '/card-harness.html') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      fs.createReadStream(CARD_HARNESS_HTML_PATH).pipe(res);
      return;
    }

    // Simulated HA-restart window: every fraimic endpoint answers 503
    // (with a JSON body -- deliberately, so tests prove an error status
    // that PARSES still never reads as real data) until setFailing(false).
    if (failing && p.startsWith('/api/digital_frames/')) {
      return json(res, 503, { message: 'Home Assistant is starting up' });
    }

    if (p === '/api/digital_frames/frames') {
      return json(res, 200, { frames });
    }
    if (p === '/api/digital_frames/discovery/scan' && req.method === 'POST') {
      return json(res, 200, { success: true });
    }
    if (p === '/api/digital_frames/onboarding') {
      // A broken flag endpoint that still returns JSON -- the panel must
      // treat this as unknown (fail closed), never as complete: false.
      if (onboardingBroken) return json(res, 500, { message: 'flag store unavailable' });
      if (req.method === 'POST') {
        onboardingComplete = true;
        return json(res, 200, { success: true, complete: true });
      }
      return json(res, 200, { complete: onboardingComplete });
    }
    if (p === '/api/digital_frames/update' || p === '/api/digital_frames/update/check') {
      return json(res, 200, { ...updateState });
    }
    if (p === '/api/digital_frames/update/dismiss' && req.method === 'POST') {
      const body = await readJsonBody(req);
      const version = (body && body.version) || updateState.latest;
      updateDismisses.push({ version });
      updateState = {
        ...updateState,
        banner_visible: false,
        banner_dismissed_version: version,
      };
      return json(res, 200, { success: true, dismissed_version: version });
    }
    if (p === '/api/digital_frames/update/install' && req.method === 'POST') {
      const body = await readJsonBody(req);
      updateInstalls.push(body || {});
      const ver = (body && body.version) || updateState.latest;
      updateState = {
        ...updateState,
        installed: ver,
        disk: ver,
        update_available: false,
        banner_visible: false,
        needs_restart: true,
      };
      return json(res, 200, {
        success: true,
        method: 'github',
        installed: ver,
        disk: ver,
        running: updateState.running,
        needs_restart: true,
        message: `Digital Frames ${ver} is on disk. Restart Home Assistant to load it.`,
      });
    }
    if (p === '/api/digital_frames/update/restart' && req.method === 'POST') {
      return json(res, 200, { success: true, message: 'Home Assistant is restarting…' });
    }

    // --- HA config/options flow API (see state machine above) -----------
    if (p === '/api/config/config_entries/flow' && req.method === 'POST') {
      await readJsonBody(req);
      const flowId = `flow_${nextFlowId++}`;
      const step = flowSteps.user(flowId);
      activeFlows[flowId] = step;
      return json(res, 200, step);
    }
    if (p === '/api/config/config_entries/options/flow' && req.method === 'POST') {
      const body = await readJsonBody(req);
      const flowId = `oflow_${nextFlowId++}`;
      const step = { ...flowSteps.optionsInit(flowId), handler: body.handler };
      activeFlows[flowId] = step;
      return json(res, 200, step);
    }
    const flowMatch = p.match(/^\/api\/config\/config_entries\/(?:options\/)?flow\/([^/]+)$/);
    if (flowMatch) {
      const flowId = flowMatch[1];
      if (!activeFlows[flowId]) return json(res, 404, { message: 'Invalid flow specified' });
      if (req.method === 'GET') return json(res, 200, activeFlows[flowId]);
      if (req.method === 'DELETE') {
        flowDeletes.push(flowId);
        delete activeFlows[flowId];
        return json(res, 200, { success: true });
      }
      if (req.method === 'POST') {
        const body = await readJsonBody(req);
        flowSubmissions.push({ flow_id: flowId, body });
        const next = advanceConfigFlow(flowId, body);
        if (!next) return json(res, 400, { message: 'no next step' });
        if (next.type === 'create_entry') delete activeFlows[flowId];
        else activeFlows[flowId] = next;
        return json(res, 200, next);
      }
    }
    const entryMatch = p.match(/^\/api\/config\/config_entries\/entry\/([^/]+)$/);
    if (entryMatch && req.method === 'DELETE') {
      entryDeletes.push(entryMatch[1]);
      return json(res, 200, { require_restart: false });
    }

    if (p === '/api/digital_frames/library/list') {
      // Mirrors library_http.py's DigitalFramesLibraryListView: `album` is an
      // optional filter over the full image list, not a required param.
      // The default album 'Images' includes all images.
      const album = url.searchParams.get('album');
      const filtered = (album && album !== 'Images') ? images.filter((img) => (img.albums || []).includes(album)) : images;
      return json(res, 200, { images: filtered, backend: libraryBackend });
    }
    if (p === '/api/digital_frames/library/settings') {
      if (req.method === 'POST') {
        // Mirrors DigitalFramesLibrarySettingsView: dropbox without a token is
        // the one validation failure the panel's inline connect can hit.
        const parsed = await readJsonBody(req);
        if (parsed.backend === 'dropbox' && !parsed.access_token) {
          return json(res, 400, { message: 'Dropbox needs an access token' });
        }
        libraryBackend = parsed.backend;
        return json(res, 200, { success: true, backend: libraryBackend });
      }
      return json(res, 200, { backend: libraryBackend });
    }
    if (p === '/api/digital_frames/library/albums') return json(res, 200, { albums });
    if (p === '/api/digital_frames/scene_packs') return json(res, 200, { packs: scenePacks });
    const installMatch = p.match(/^\/api\/digital_frames\/scene_packs\/([^/]+)\/install$/);
    if (installMatch && req.method === 'POST') {
      const parsed = await readJsonBody(req);
      installCalls.push({ pack_id: installMatch[1], config: parsed.config || {} });
      return json(res, 200, { success: true, pack_id: installMatch[1], type: 'widget' });
    }

    if (p === '/api/digital_frames/library/crop') {
      // Mirrors DigitalFramesLibraryCropView: save/clear a crop rect keyed by
      // effective resolution, returning the updated image record.
      const parsed = await readJsonBody(req);
      const image = images.find((img) => img.image_id === parsed.image_id);
      if (!image) return json(res, 404, { message: `Image '${parsed.image_id}' not found` });
      image.crops = image.crops || {};
      const key = `${parsed.width}x${parsed.height}`;
      if (req.method === 'POST') {
        cropSaves.push({ image_id: parsed.image_id, width: parsed.width, height: parsed.height, crop_box: parsed.crop_box });
        image.crops[key] = parsed.crop_box;
      } else if (req.method === 'DELETE') {
        cropDeletes.push({ image_id: parsed.image_id, width: parsed.width, height: parsed.height });
        delete image.crops[key];
      }
      return json(res, 200, { success: true, image });
    }

    if (p.startsWith('/api/digital_frames/library/image/') && p.endsWith('/voice_name')) {
      const parts = p.split('/');
      const imageId = parts[parts.length - 2];
      const parsed = await readJsonBody(req);
      const image = images.find(img => img.image_id === imageId);
      if (image) {
        image.voice_name = parsed.voice_name;
      }
      return json(res, 200, { success: true, image });
    }

    if (p.startsWith('/api/digital_frames/library/image/') && p.endsWith('/tags')) {
      const parts = p.split('/');
      const imageId = parts[parts.length - 2];
      const parsed = await readJsonBody(req);
      const image = images.find(img => img.image_id === imageId);
      if (image) {
        image.tags = parsed.tags;
      }
      return json(res, 200, { success: true, image });
    }

    if (p.startsWith('/api/digital_frames/library/image/') && p.endsWith('/albums')) {
      const parts = p.split('/');
      const imageId = parts[parts.length - 2];
      const parsed = await readJsonBody(req);
      const image = images.find(img => img.image_id === imageId);
      if (image) {
        image.albums = parsed.albums;
      }
      return json(res, 200, { success: true, image });
    }

    if (p.startsWith('/api/digital_frames/library/image/')) {
      res.writeHead(200, { 'Content-Type': 'image/png' });
      res.end(TINY_PNG);
      return;
    }

    if (p.match(/^\/api\/digital_frames\/frame\/[^/]+\/thumbnail$/)) {
      // The frame's own render preview (uploads, xOTD/skill text renders) --
      // ETag'd like the real DigitalFramesFrameThumbnailView.
      const etag = '"tiny-png"';
      if (req.headers['if-none-match'] === etag) {
        res.writeHead(304, { ETag: etag });
        res.end();
        return;
      }
      res.writeHead(200, { 'Content-Type': 'image/png', ETag: etag });
      res.end(TINY_PNG);
      return;
    }

    if (p === '/api/digital_frames/send_image' && req.method === 'POST') {
      // Raw upload → convert → send (the per-tile "Upload a photo" path).
      const form = await readFormBody(req);
      rawSends.push({ entity_id: form.entity_id, has_image: 'image' in form });
      return json(res, 200, { success: true, bytes_sent: 960000 });
    }

    if (p === '/api/digital_frames/library/send' && req.method === 'POST') {
      // Only parses URL-encoded bodies (what the ?packtest modal sends);
      // FormData/multipart senders aren't exercised through this route yet.
      const form = await readFormBody(req);
      sends.push({ entity_id: form.entity_id, image_id: form.image_id, packer: form.packer });
      const body = { success: true, bytes_sent: 960000 };
      if (form.packer) body.packer = form.packer;
      return json(res, 200, body);
    }

    if (p === '/api/digital_frames/scenes') {
      if (req.method === 'GET') return json(res, 200, { scenes: sceneList });
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        if (!parsed.mappings || !Object.keys(parsed.mappings).length) {
          return json(res, 400, { message: 'A scene needs at least one frame/image assignment' });
        }
        const scene = { scene_id: `scene_${nextSceneId++}`, name: parsed.name, mappings: parsed.mappings, created_at: 0, album: parsed.album || null, source: 'user' };
        sceneList.push(scene);
        return json(res, 200, { success: true, scene });
      }
    }
    const sceneMatch = p.match(/^\/api\/digital_frames\/scenes\/([^/]+)$/);
    if (sceneMatch) {
      const sceneId = sceneMatch[1];
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const scene = sceneList.find((s) => s.scene_id === sceneId);
        if (!scene) return json(res, 400, { message: `Scene '${sceneId}' not found` });
        if (!parsed.mappings || !Object.keys(parsed.mappings).length) {
          return json(res, 400, { message: 'A scene needs at least one frame/image assignment' });
        }
        scene.name = parsed.name;
        scene.mappings = parsed.mappings;
        scene.album = parsed.album || null;
        return json(res, 200, { success: true, scene });
      }
      if (req.method === 'DELETE') {
        sceneList = sceneList.filter((s) => s.scene_id !== sceneId);
        return json(res, 200, { success: true });
      }
    }

    if (p === '/api/digital_frames/schedules') {
      if (req.method === 'GET') {
        return json(res, 200, {
          schedules: scheduleList.map((s) => ({ next_fire_at: null, ...s })),
        });
      }
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        // Mirror ScheduleManager's creation-time validation shape (name,
        // action union, trigger union) closely enough that dialog error
        // paths are drivable from tests.
        if (!parsed.name || !parsed.name.trim()) {
          return json(res, 400, { message: "Schedule name can't be empty" });
        }
        if (!parsed.action || !['scene', 'image'].includes(parsed.action.type)) {
          return json(res, 400, { message: 'Invalid action' });
        }
        if (!parsed.trigger || !['once', 'recurring'].includes(parsed.trigger.type)) {
          return json(res, 400, { message: 'Invalid trigger' });
        }
        const schedule = {
          schedule_id: `schedule_${nextScheduleId++}`,
          name: parsed.name,
          enabled: parsed.enabled !== false,
          action: parsed.action,
          trigger: parsed.trigger,
          created_at: '2026-01-01T00:00:00',
          last_fired_at: null,
          status: 'pending',
          fired_late: false,
        };
        scheduleList.push(schedule);
        return json(res, 200, { success: true, schedule });
      }
    }
    const scheduleMatch = p.match(/^\/api\/digital_frames\/schedules\/([^/]+)$/);
    if (scheduleMatch) {
      const scheduleId = scheduleMatch[1];
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const schedule = scheduleList.find((s) => s.schedule_id === scheduleId);
        if (!schedule) return json(res, 404, { message: `Schedule '${scheduleId}' not found` });
        for (const key of ['name', 'action', 'trigger', 'enabled']) {
          if (key in parsed) schedule[key] = parsed[key];
        }
        if ('action' in parsed || 'trigger' in parsed) {
          schedule.status = 'pending';
          schedule.fired_late = false;
        }
        return json(res, 200, { success: true, schedule });
      }
      if (req.method === 'DELETE') {
        scheduleList = scheduleList.filter((s) => s.schedule_id !== scheduleId);
        return json(res, 200, { success: true });
      }
    }

    if (p === '/api/digital_frames/messages/send' && req.method === 'POST') {
      const parsed = await readJsonBody(req);
      if (!parsed.message_text) return json(res, 400, { message: 'message_text is required' });
      if (!parsed.target || !['frame', 'scene', 'wall'].includes(parsed.target.type)) {
        return json(res, 400, { message: 'target must be {type: frame|scene|wall, ...}' });
      }
      if (parsed.save_to_library && parsed.target.type === 'scene') {
        return json(res, 400, { message: "save_to_library isn't supported for a scene target" });
      }
      messageSendCalls.push(parsed);
      return json(res, 200, {
        success: true,
        results: [{ entry_id: 'entry_1', success: true }],
        saved_image_id: parsed.save_to_library ? 'uploaded_1' : null,
      });
    }

    const skillSendMatch = p.match(/^\/api\/digital_frames\/skills\/([^/]+)\/send$/);
    if (skillSendMatch && req.method === 'POST') {
      const skillId = skillSendMatch[1];
      const skill = skillList.find((s) => s.skill_id === skillId);
      if (!skill) return json(res, 404, { message: `Skill '${skillId}' not found` });
      const parsed = await readJsonBody(req);
      if (!parsed.entry_id) return json(res, 400, { message: 'Request body needs an entry_id' });
      skillSendCalls.push({ skill_id: skillId, entry_id: parsed.entry_id });
      return json(res, 200, { success: true, results: [{ entry_id: parsed.entry_id, success: true }] });
    }
    if (p === '/api/digital_frames/skills') {
      if (req.method === 'GET') {
        return json(res, 200, { skills: skillList });
      }
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const validModes = ['joke', 'quote', 'scripture', 'word', 'image_feed', 'image_album'];
        if (!parsed.name) return json(res, 400, { message: "Skill name can't be empty" });
        if (!validModes.includes(parsed.content_mode)) {
          return json(res, 400, { message: `Invalid content_mode: ${parsed.content_mode}` });
        }
        const skill = {
          skill_id: `skill_${nextSkillId++}`,
          name: parsed.name,
          content_mode: parsed.content_mode,
          config: parsed.config || {},
          created_at: '2026-01-01T00:00:00',
        };
        skillList.push(skill);
        return json(res, 200, { success: true, skill });
      }
    }
    const skillMatch = p.match(/^\/api\/digital_frames\/skills\/([^/]+)$/);
    if (skillMatch) {
      const skillId = skillMatch[1];
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const skill = skillList.find((s) => s.skill_id === skillId);
        if (!skill) return json(res, 404, { message: `Skill '${skillId}' not found` });
        for (const key of ['name', 'content_mode', 'config']) {
          if (key in parsed) skill[key] = parsed[key];
        }
        return json(res, 200, { success: true, skill });
      }
      if (req.method === 'DELETE') {
        skillList = skillList.filter((s) => s.skill_id !== skillId);
        return json(res, 200, { success: true });
      }
    }

    if (p === '/api/digital_frames/walls') {
      if (req.method === 'GET') return json(res, 200, { walls: wallList });
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const wall = { wall_id: `wall_${nextWallId++}`, name: parsed.name, placements: parsed.placements || {}, excluded: [], created_at: 0 };
        wallList.push(wall);
        return json(res, 200, { success: true, wall });
      }
    }
    const wallMatch = p.match(/^\/api\/digital_frames\/walls\/(.+)$/);
    if (wallMatch) {
      const wallId = wallMatch[1];
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const wall = wallList.find((w) => w.wall_id === wallId);
        if (!wall) return json(res, 400, { message: 'not found' });
        wall.name = parsed.name;
        wall.placements = parsed.placements || {};
        // Mirrors WallManager.async_save_wall: absent = keep stored.
        if (Array.isArray(parsed.excluded)) wall.excluded = parsed.excluded;
        return json(res, 200, { success: true, wall });
      }
      if (req.method === 'DELETE') {
        wallList = wallList.filter((w) => w.wall_id !== wallId);
        return json(res, 200, { success: true });
      }
    }

    res.writeHead(404);
    res.end('not found');
  });

  return {
    async start() {
      await new Promise((resolve) => server.listen(0, resolve));
      const port = server.address().port;
      return `http://localhost:${port}`;
    },
    async stop() {
      if (typeof server.closeAllConnections === 'function') {
        server.closeAllConnections();
      }
      await new Promise((resolve) => server.close(resolve));
    },
    requestLog,
    sends,
    rawSends,
    installCalls,
    cropSaves,
    cropDeletes,
    flowSubmissions,
    flowDeletes,
    entryDeletes,
    get scenes() { return sceneList; },
    get schedules() { return scheduleList; },
    get skills() { return skillList; },
    skillSendCalls,
    messageSendCalls,
    get walls() { return wallList; },
    setFailing(value) { failing = value; },
    get onboardingComplete() { return onboardingComplete; },
    get libraryBackend() { return libraryBackend; },
    updateDismisses,
    updateInstalls,
    get updateState() { return updateState; },
  };
}

module.exports = { createMockServer };
