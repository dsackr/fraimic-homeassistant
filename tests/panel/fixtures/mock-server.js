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

// frames: [{ entry_id, title, width, height, orientation, ... }]
// scenes: [{ scene_id, name, mappings, album, source }]
// images: [{ image_id, filename, albums }]
function createMockServer({ frames = [], scenes = [], images = [] } = {}) {
  let sceneList = scenes.map((s) => ({ created_at: 0, album: null, source: 'user', ...s }));
  let wallList = [];
  let nextWallId = 1;
  let nextSceneId = sceneList.length + 1;
  const requestLog = [];

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

    if (p === '/api/fraimic/library/list') return json(res, 200, { images, backend: 'local' });
    if (p === '/api/fraimic/library/settings') return json(res, 200, { backend: 'local' });
    if (p === '/api/fraimic/library/albums') return json(res, 200, { albums: [] });
    if (p === '/api/fraimic/scene_packs') return json(res, 200, { packs: [] });

    if (p.startsWith('/api/fraimic/library/image/')) {
      res.writeHead(200, { 'Content-Type': 'image/png' });
      res.end(TINY_PNG);
      return;
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
      await new Promise((resolve) => server.close(resolve));
    },
    requestLog,
    get scenes() { return sceneList; },
    get walls() { return wallList; },
  };
}

module.exports = { createMockServer };
