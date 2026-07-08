// A minimal in-memory stand-in for the Fraimic HTTP API + Home Assistant's
// own frame/entity registries, just enough for fraimic-panel.js's init
// sequence and the Frames/Walls/Scenes flows to run against in a real
// browser. Each test gets its own instance (see createMockServer) so state
// never leaks between tests.

const path = require('path');
const http = require('http');
const fs = require('fs');

const PANEL_JS_PATH = path.join(__dirname, '..', '..', '..', 'custom_components', 'fraimic', 'fraimic-panel.js');
const HARNESS_HTML_PATH = path.join(__dirname, 'harness.html');
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
// field values (entity_id, image_id, packer) out of a FormData POST body.
function parseMultipartFields(buf) {
  const text = buf.toString('latin1');
  const result = {};
  const re = /name="([^"]+)"\r\n\r\n([\s\S]*?)\r\n--/g;
  let m;
  while ((m = re.exec(text))) {
    result[m[1]] = m[2];
  }
  return result;
}

// frames: [{ entry_id, title, width, height, orientation, ... }]
// scenes: [{ scene_id, name, mappings, album, source }]
// images: [{ image_id, filename, albums: [albumName, ...] }]
// albums: [{ name, count, cover_image_id }]
// walls: [{ wall_id, name, placements }]
// scenePacks: [{ id, name, categories, ... }]
function createMockServer({ frames = [], scenes = [], images = [], albums = [], walls = [], scenePacks = [], discoveredFlows = [] } = {}) {
  let sceneList = scenes.map((s) => ({ created_at: 0, album: null, source: 'user', ...s }));
  // The backend guarantees the default "All Frames" wall exists with a
  // placement for every configured frame -- mirror that here unless a test
  // seeds its own default wall record.
  let wallList = walls.map((w) => ({ created_at: 0, placements: {}, kind: 'custom', ...w }));
  if (!wallList.some((w) => w.kind === 'default')) {
    const defaultPlacements = {};
    frames.forEach((f, i) => { defaultPlacements[f.entry_id] = { x: i * 160, y: 0 }; });
    wallList.unshift({
      wall_id: 'default', name: 'All Frames', kind: 'default',
      placements: defaultPlacements, created_at: 0,
    });
  }
  let nextWallId = wallList.length + 1;
  let nextSceneId = sceneList.length + 1;
  const requestLog = [];
  const sends = []; // { entity_id, image_id, packer } per /library/send POST

  // --- Embedded config/options flow state machine -----------------------
  // Mirrors FraimicConfigFlow's real step graph (user → pick_device →
  // name_device → create_entry, with a cannot_connect error branch) and
  // FraimicOptionsFlow's single init step carrying one field of each
  // serialized type the renderer must handle.
  const flowSubmissions = [];   // { flow_id, body } per step POST
  const flowDeletes = [];       // flow_id per flow DELETE
  const entryDeletes = [];      // entry_id per config entry DELETE
  const activeFlows = {};       // flow_id → current step result
  let nextFlowId = 1;

  const flowSteps = {
    user: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'fraimic', step_id: 'user',
      data_schema: [{ name: 'host', type: 'string', optional: true, default: '' }],
      errors: {}, description_placeholders: null, last_step: false,
    }),
    userCannotConnect: (flowId) => ({
      ...flowSteps.user(flowId), errors: { host: 'cannot_connect' },
    }),
    pick_device: (flowId) => ({
      type: 'form', flow_id: flowId, handler: 'fraimic', step_id: 'pick_device',
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
      type: 'form', flow_id: flowId, handler: 'fraimic', step_id: 'manual',
      data_schema: [{ name: 'host', type: 'string', required: true }],
      errors: {}, description_placeholders: null, last_step: false,
    }),
    name_device: (flowId, host) => ({
      type: 'form', flow_id: flowId, handler: 'fraimic', step_id: 'name_device',
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
    if (current.step_id === 'user') {
      if (body.host === '') return flowSteps.pick_device(flowId);
      if (body.host === '10.0.0.99') return flowSteps.userCannotConnect(flowId);
      return flowSteps.name_device(flowId, body.host);
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

    if (p === '/fraimic-panel.js') {
      res.writeHead(200, { 'Content-Type': 'application/javascript' });
      fs.createReadStream(PANEL_JS_PATH).pipe(res);
      return;
    }
    if (p === '/' || p === '/harness.html') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      fs.createReadStream(HARNESS_HTML_PATH).pipe(res);
      return;
    }

    if (p === '/api/fraimic/frames') {
      return json(res, 200, { frames });
    }
    if (p === '/api/fraimic/discovery/scan' && req.method === 'POST') {
      return json(res, 200, { success: true });
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

    if (p === '/api/fraimic/library/list') {
      // Mirrors library_http.py's FraimicLibraryListView: `album` is an
      // optional filter over the full image list, not a required param.
      const album = url.searchParams.get('album');
      const filtered = album ? images.filter((img) => (img.albums || []).includes(album)) : images;
      return json(res, 200, { images: filtered, backend: 'local' });
    }
    if (p === '/api/fraimic/library/settings') return json(res, 200, { backend: 'local' });
    if (p === '/api/fraimic/library/albums') return json(res, 200, { albums });
    if (p === '/api/fraimic/scene_packs') return json(res, 200, { packs: scenePacks });

    if (p.startsWith('/api/fraimic/library/image/')) {
      res.writeHead(200, { 'Content-Type': 'image/png' });
      res.end(TINY_PNG);
      return;
    }

    if (p === '/api/fraimic/library/send' && req.method === 'POST') {
      // Only parses URL-encoded bodies (what the ?packtest modal sends);
      // FormData/multipart senders aren't exercised through this route yet.
      const form = await readFormBody(req);
      sends.push({ entity_id: form.entity_id, image_id: form.image_id, packer: form.packer });
      const body = { success: true, bytes_sent: 960000 };
      if (form.packer) body.packer = form.packer;
      return json(res, 200, body);
    }

    if (p === '/api/fraimic/scenes') {
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
    const sceneMatch = p.match(/^\/api\/fraimic\/scenes\/([^/]+)$/);
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

    if (p === '/api/fraimic/walls') {
      if (req.method === 'GET') return json(res, 200, { walls: wallList });
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const wall = { wall_id: `wall_${nextWallId++}`, name: parsed.name, placements: parsed.placements || {}, created_at: 0 };
        wallList.push(wall);
        return json(res, 200, { success: true, wall });
      }
    }
    const wallMatch = p.match(/^\/api\/fraimic\/walls\/(.+)$/);
    if (wallMatch) {
      const wallId = wallMatch[1];
      if (req.method === 'POST') {
        const parsed = await readJsonBody(req);
        const wall = wallList.find((w) => w.wall_id === wallId);
        if (!wall) return json(res, 400, { message: 'not found' });
        wall.name = parsed.name;
        wall.placements = parsed.placements || {};
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
    flowSubmissions,
    flowDeletes,
    entryDeletes,
    get scenes() { return sceneList; },
    get walls() { return wallList; },
  };
}

module.exports = { createMockServer };
