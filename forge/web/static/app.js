import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ================================================================ state & helpers
const S = {
  project: null, part: null, schema: null, params: {}, defaults: {}, source: '', dirty: false,
  topo: null, bbox: null, size: 50, violations: [],
  filter: 'any', selection: [],           // [{kind:'faces'|'edges'|'bodies', index, expr?, stable?}]
  hover: null, hiddenBodies: new Set(), measurePts: null, measureText: '',
  dialog: null,                            // {cmd, values, activeField, code}
  commands: [], buildTimer: null, building: false, queued: false, hasFit: false,
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const status = (t, bad = false) => { $('status').textContent = t; $('status').style.color = bad ? 'var(--err)' : 'var(--muted)'; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (url, body) => {
  if (S.project && url.startsWith('/api/') && !url.startsWith('/api/projects')) url += (url.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(S.project);
  if (body && S.project) body = { project: S.project, ...body };
  const r = await fetch(url, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), j);
  return j;
};

// ================================================================ three.js scene
const viewer = $('viewer');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.localClippingEnabled = true;
renderer.domElement.className = 'main';
viewer.insertBefore(renderer.domElement, viewer.firstChild);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
const orthoCam = new THREE.OrthographicCamera(-50, 50, 50, -50, -2000, 2000);
camera.up.set(0, 0, 1); orthoCam.up.set(0, 0, 1);
let controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x404060, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(80, -120, 160); scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(-100, 80, 40); scene.add(fill);
const grid = new THREE.GridHelper(400, 40, 0x3a4150, 0x262b33); grid.rotation.x = Math.PI / 2; scene.add(grid);
const axes = new THREE.AxesHelper(20); scene.add(axes);
const clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e9);
const matBody = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05, roughness: 0.55, side: THREE.DoubleSide, clippingPlanes: [clipPlane] });
const matEdge = new THREE.LineBasicMaterial({ color: 0x1b1e24, clippingPlanes: [clipPlane] });
const matEdgeSel = new THREE.LineBasicMaterial({ color: 0x4cc2ff, depthTest: false });
const group = new THREE.Group(); scene.add(group);           // one Mesh per body
const edgeGroup = new THREE.Group(); scene.add(edgeGroup);   // all B-rep edges, one LineSegments
const selGroup = new THREE.Group(); scene.add(selGroup);     // selected edges / measure overlay
const markerGroup = new THREE.Group(); scene.add(markerGroup);
const planeGroup = new THREE.Group(); scene.add(planeGroup); // origin planes
const COL = { body: new THREE.Color(0xc9cdd6), over: new THREE.Color(0xef6a4a), sel: new THREE.Color(0x4cc2ff), hover: new THREE.Color(0x9adcff), preview: new THREE.Color(0xa8e6bf) };

function activeCam() { return $('btnOrtho').classList.contains('active') ? orthoCam : camera; }
function resize() {
  const w = viewer.clientWidth, h = viewer.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  const a = w / h, z = orthoCam.top; orthoCam.left = -z * a; orthoCam.right = z * a; orthoCam.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewer); resize();

// ---- mesh building: one Mesh per body, per-vertex colours so faces can be highlighted
let faceRange = {};   // faceId -> {mesh, start (vertex index), count, base [r,g,b]}
let edgeOwner = [];   // segment index -> edge id
function setTopo(topo, { preview = false } = {}) {
  S.topo = topo; S.bbox = topo.bbox; S.size = Math.max(1, ...[0, 1, 2].map((i) => topo.bbox[1][i] - topo.bbox[0][i]));
  group.clear(); edgeGroup.clear(); selGroup.clear(); faceRange = {};
  const V = topo.vertices, I = topo.indices;
  const byBody = new Map();
  for (const f of topo.faces) { if (!byBody.has(f.body)) byBody.set(f.body, []); byBody.get(f.body).push(f); }
  const zmin = topo.bbox[0][2];
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3(), ab = new THREE.Vector3(), ac = new THREE.Vector3();
  for (const [bid, faces] of byBody) {
    const pos = [], col = [];
    let cursor = 0;
    for (const f of faces) {
      const start = cursor;
      let cc = COL.body;
      for (let t = f.tri_start; t < f.tri_start + f.tri_count; t++) {
        const i0 = I[t * 3], i1 = I[t * 3 + 1], i2 = I[t * 3 + 2];
        a.set(V[i0 * 3], V[i0 * 3 + 1], V[i0 * 3 + 2]); b.set(V[i1 * 3], V[i1 * 3 + 1], V[i1 * 3 + 2]); c.set(V[i2 * 3], V[i2 * 3 + 1], V[i2 * 3 + 2]);
        ab.copy(b).sub(a); ac.copy(c).sub(a); n.copy(ab).cross(ac).normalize();
        const onBed = Math.max(a.z, b.z, c.z) < zmin + 1e-3;
        const over = !preview && n.z < -1e-3 && -n.z > 0.7071 && !onBed;   // steeper than 45° from vertical
        cc = preview ? COL.preview : over ? COL.over : COL.body;
        pos.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
        for (let k = 0; k < 3; k++) col.push(cc.r, cc.g, cc.b);
        cursor += 3;
      }
      faceRange[f.id] = { body: bid, start, count: cursor - start, base: [cc.r, cc.g, cc.b], mesh: null };
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    g.computeVertexNormals();
    const mesh = new THREE.Mesh(g, matBody); mesh.userData.body = bid; mesh.visible = !S.hiddenBodies.has(bid);
    group.add(mesh);
    for (const f of faces) faceRange[f.id].mesh = mesh;
  }
  const segs = []; edgeOwner = [];
  topo.polylines.forEach((poly, ei) => { for (let i = 0; i + 5 < poly.length; i += 3) { segs.push(poly[i], poly[i + 1], poly[i + 2], poly[i + 3], poly[i + 4], poly[i + 5]); edgeOwner.push(ei); } });
  const eg = new THREE.BufferGeometry(); eg.setAttribute('position', new THREE.Float32BufferAttribute(segs, 3));
  edgeGroup.add(new THREE.LineSegments(eg, matEdge));
  applyShading(); updateClip();
  if (!preview) {
    S.selection = S.selection.filter((s) => (s.kind === 'faces' ? topo.faces[s.index] : s.kind === 'edges' ? topo.edges[s.index] : topo.bodies[s.index]));
  }
  paintSelection();
}

function paintFace(id, color) {
  const r = faceRange[id]; if (!r || !r.mesh) return;
  const arr = r.mesh.geometry.attributes.color.array;
  for (let i = 0; i < r.count; i++) { const o = (r.start + i) * 3; if (color) { arr[o] = color.r; arr[o + 1] = color.g; arr[o + 2] = color.b; } else { arr[o] = r.base[0]; arr[o + 1] = r.base[1]; arr[o + 2] = r.base[2]; } }
  r.mesh.geometry.attributes.color.needsUpdate = true;
}
function paintSelection() {
  if (!S.topo) return;
  for (const f of S.topo.faces) paintFace(f.id, null);
  selGroup.children.filter((o) => o.userData.sel).forEach((o) => selGroup.remove(o));
  for (const s of S.selection) {
    if (s.kind === 'faces') paintFace(s.index, COL.sel);
    else if (s.kind === 'bodies') for (const f of S.topo.faces) if (f.body === s.index) paintFace(f.id, COL.sel);
    else if (s.kind === 'edges') { const poly = S.topo.polylines[s.index] || []; const pts = []; for (let i = 0; i < poly.length; i += 3) pts.push(new THREE.Vector3(poly[i], poly[i + 1], poly[i + 2])); const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), matEdgeSel); l.renderOrder = 20; l.userData.sel = true; selGroup.add(l); }
  }
  if (S.hover && S.hover.kind === 'faces' && !S.selection.some((s) => s.kind === 'faces' && s.index === S.hover.index)) paintFace(S.hover.index, COL.hover);
  renderSelPanel(); renderTree();
}

// ---- picking
const ray = new THREE.Raycaster();
function pick(ev) {
  if (!S.topo) return null;
  const r = renderer.domElement.getBoundingClientRect();
  const m = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(m, activeCam());
  ray.params.Line.threshold = S.size * 0.012;
  const filt = S.dialog?.activeField?.select || S.filter;
  let best = null;
  if (filt === 'any' || filt === 'edges') {
    const eh = ray.intersectObjects(edgeGroup.children, false)[0];
    if (eh) best = { kind: 'edges', index: edgeOwner[Math.floor(eh.index / 2)], dist: eh.distance - S.size * 0.01, point: eh.point };
  }
  if (filt !== 'edges') {
    const fh = ray.intersectObjects(group.children.filter((o) => o.visible), false)[0];
    if (fh && (!best || fh.distance < best.dist)) {
      const mesh = fh.object, v0 = fh.faceIndex * 3;
      let fid = null;
      for (const f of S.topo.faces) { const rr = faceRange[f.id]; if (rr.mesh === mesh && v0 >= rr.start && v0 < rr.start + rr.count) { fid = f.id; break; } }
      if (fid != null) best = { kind: filt === 'bodies' ? 'bodies' : 'faces', index: filt === 'bodies' ? mesh.userData.body : fid, dist: fh.distance, point: fh.point };
    }
  }
  return best;
}
let downAt = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointermove', (e) => {
  if (downAt) return;
  const h = pick(e);
  const changed = (h?.kind !== S.hover?.kind) || (h?.index !== S.hover?.index);
  if (changed) { S.hover = h ? { kind: h.kind, index: h.index } : null; paintSelection(); renderer.domElement.style.cursor = h ? 'pointer' : ''; }
});
renderer.domElement.addEventListener('pointerup', async (e) => {
  const was = downAt; downAt = null;
  if (!was || Math.hypot(e.clientX - was[0], e.clientY - was[1]) > 4) return;   // dragging = orbit
  if (e.button === 2) { showCtx(e); return; }
  if (e.button !== 0) return;
  const h = pick(e);
  if (S.measurePts) { if (h) addMeasurePoint(h.point); return; }
  if (!h) { if (!e.shiftKey && !e.ctrlKey) { S.selection = []; paintSelection(); } return; }
  const already = S.selection.findIndex((s) => s.kind === h.kind && s.index === h.index);
  if (e.shiftKey || e.ctrlKey || S.dialog?.activeField?.multi) { if (already >= 0) S.selection.splice(already, 1); else S.selection.push({ kind: h.kind, index: h.index }); }
  else S.selection = (already >= 0 && S.selection.length === 1) ? [] : [{ kind: h.kind, index: h.index }];
  paintSelection();
  await resolveSelectors();
  if (S.dialog?.activeField) dialogTakeSelection();
});
renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

async function resolveSelectors() {
  for (const s of S.selection) {
    if (s.expr || s.kind === 'bodies') continue;
    try { const r = await api('/api/selector', { name: S.part, params: S.params, kind: s.kind, index: s.index }); s.expr = r.expr; s.stable = r.stable; }
    catch (e) { s.expr = `part.${s.kind}()[${s.index}]`; s.stable = false; }
  }
  renderSelPanel();
}
function renderSelPanel() {
  const p = $('selpanel');
  if (!S.selection.length && !S.measureText) { p.classList.remove('show'); return; }
  p.classList.add('show');
  const rows = S.selection.map((s) => {
    const info = s.kind === 'faces' ? S.topo.faces[s.index] : s.kind === 'edges' ? S.topo.edges[s.index] : S.topo.bodies[s.index];
    if (!info) return '';
    let desc = '';
    if (s.kind === 'faces') desc = `${info.type} face · ${info.area} mm²` + (info.radius ? ` · R${info.radius}` : '') + (info.normal ? ` · normal (${info.normal.join(', ')})` : '');
    else if (s.kind === 'edges') desc = `${info.type} edge · ${info.length} mm` + (info.radius ? ` · R${info.radius} (Ø${(info.radius * 2).toFixed(2)})` : '');
    else desc = `body ${info.label} · ${info.volume} mm³ · ${info.faces} faces`;
    return `<div>${esc(desc)}</div>` + (s.expr ? `<div class="expr" title="click to copy" data-expr="${esc(s.expr)}">${esc(s.expr)}${s.stable ? '' : ' <span style="color:var(--warn)">(index-based)</span>'}</div>` : '');
  }).join('');
  p.innerHTML = rows + (S.measureText ? `<div class="meas">${esc(S.measureText)}</div>` : '') + `<div style="color:var(--muted);font-size:10px;margin-top:4px">shift-click adds · I measure · right-click for commands · Esc clears</div>`;
  p.querySelectorAll('.expr').forEach((el) => (el.onclick = () => { navigator.clipboard?.writeText(el.dataset.expr); status('selector copied to clipboard'); }));
}

// ---- views / camera
function center(bb) { return new THREE.Vector3((bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2, (bb[0][2] + bb[1][2]) / 2); }
function setCameraDir(v, c, size) {
  if (!S.bbox) return;
  c = c || center(S.bbox); size = size || S.size;
  const d = size * 1.9 + 10;
  const p = c.clone().add(v.clone().normalize().multiplyScalar(d));
  camera.position.copy(p); orthoCam.position.copy(p);
  orthoCam.top = size * 0.8; orthoCam.bottom = -size * 0.8; resize();
  controls.target.copy(c); controls.update();
  grid.position.set(c.x, c.y, S.bbox[0][2] - 0.05);
}
const DIRS = { iso: [1, -1.2, 0.9], front: [0, -1, 0.0001], back: [0, 1, 0.0001], top: [0.0001, -0.0001, 1], bottom: [0.0001, -0.0001, -1], right: [1, 0, 0.0001], left: [-1, 0, 0.0001] };
function fitView(name = 'iso') { setCameraDir(new THREE.Vector3(...(DIRS[name] || DIRS.iso))); }
function fitKeep() { if (!S.bbox) return; setCameraDir(activeCam().position.clone().sub(controls.target)); }
document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => fitView(b.dataset.view)));
$('btnFit').onclick = fitKeep;
$('btnZoomSel').onclick = () => { const s = S.selection[0]; if (!s) return; const info = s.kind === 'faces' ? S.topo.faces[s.index] : s.kind === 'bodies' ? S.topo.bodies[s.index] : null; if (!info?.bbox) return; const [mn, mx] = info.bbox; setCameraDir(activeCam().position.clone().sub(controls.target), center(info.bbox), Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], 2)); };
$('btnOrtho').onclick = () => { const ortho = $('btnOrtho').classList.toggle('active'); const from = ortho ? camera : orthoCam, to = ortho ? orthoCam : camera; to.position.copy(from.position); const t = controls.target.clone(); controls.dispose(); controls = new OrbitControls(to, renderer.domElement); controls.enableDamping = true; controls.target.copy(t); controls.update(); if (ortho) { orthoCam.top = from.position.distanceTo(t) * Math.tan(THREE.MathUtils.degToRad(17.5)); orthoCam.bottom = -orthoCam.top; resize(); } };
$('btnGrid').onclick = () => { grid.visible = axes.visible = $('btnGrid').classList.toggle('active'); };
$('shading').onchange = applyShading;
function applyShading() {
  const m = $('shading').value;
  matBody.wireframe = m === 'wire'; matBody.transparent = m === 'xray'; matBody.opacity = m === 'xray' ? 0.35 : 1; matBody.depthWrite = m !== 'xray'; matBody.needsUpdate = true;
  edgeGroup.children.forEach((l) => (l.visible = m === 'shaded' || m === 'xray'));
}
function updateClip() {
  const ax = $('secAxis').value;
  if (!ax || !S.bbox) { clipPlane.constant = 1e9; return; }
  const i = { x: 0, y: 1, z: 2 }[ax]; const t = $('secPos').value / 1000;
  const v = S.bbox[0][i] + (S.bbox[1][i] - S.bbox[0][i]) * t; const nrm = [0, 0, 0]; nrm[i] = -1;
  clipPlane.normal.set(...nrm); clipPlane.constant = v;
}
$('secAxis').onchange = updateClip; $('secPos').oninput = updateClip;

// ---- origin planes
function makePlanes() {
  const vis = Object.fromEntries(['XY', 'XZ', 'YZ'].map((n) => [n, planeGroup.getObjectByName(n)?.visible || false]));
  planeGroup.clear();
  const s = Math.max(S.size || 50, 20) * 1.2;
  const mk = (name, rot, color) => { const g = new THREE.PlaneGeometry(s, s); const p = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false })); p.rotation.set(...rot); p.name = name; p.visible = vis[name]; planeGroup.add(p); const e = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.5 })); e.rotation.set(...rot); e.name = name + '_e'; e.visible = vis[name]; planeGroup.add(e); };
  mk('XY', [0, 0, 0], 0x5aa5ef); mk('XZ', [Math.PI / 2, 0, 0], 0x5ad38a); mk('YZ', [0, Math.PI / 2, 0], 0xef5a5a);
}
makePlanes();

// ---- ViewCube
const cubeCanvas = $('cube');
const cubeRenderer = new THREE.WebGLRenderer({ canvas: cubeCanvas, antialias: true, alpha: true });
cubeRenderer.setPixelRatio(2); cubeRenderer.setSize(110, 110, false);
const cubeScene = new THREE.Scene();
const cubeCam = new THREE.PerspectiveCamera(30, 1, 0.1, 100); cubeCam.up.set(0, 0, 1);
cubeScene.add(new THREE.AmbientLight(0xffffff, 1.2));
function label(text) { const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d'); g.fillStyle = '#2c313a'; g.fillRect(0, 0, 128, 128); g.strokeStyle = '#5b6372'; g.lineWidth = 6; g.strokeRect(3, 3, 122, 122); g.fillStyle = '#e6e8ec'; g.font = 'bold 24px system-ui'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 64, 64); return new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c) }); }
const cubeMesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), [label('RIGHT'), label('LEFT'), label('BACK'), label('FRONT'), label('TOP'), label('BOTTOM')]);
cubeScene.add(cubeMesh);
cubeScene.add(new THREE.LineSegments(new THREE.EdgesGeometry(cubeMesh.geometry), new THREE.LineBasicMaterial({ color: 0x9aa3b2 })));
cubeCanvas.addEventListener('click', (e) => {
  const r = cubeCanvas.getBoundingClientRect();
  const m = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const rc = new THREE.Raycaster(); rc.setFromCamera(m, cubeCam);
  const h = rc.intersectObject(cubeMesh)[0]; if (!h) return;
  const p = h.point, n = h.face.normal; const dir = n.clone();
  ['x', 'y', 'z'].forEach((k) => { if (Math.abs(n[k]) < 0.5 && Math.abs(p[k]) > 0.34) dir[k] = Math.sign(p[k]); });  // near an edge/corner → that direction
  if (Math.abs(dir.x) + Math.abs(dir.y) < 1e-6) dir.y = -0.0001;
  setCameraDir(dir);
});
function renderCube() { const d = activeCam().position.clone().sub(controls.target).normalize(); cubeCam.position.copy(d.multiplyScalar(3.2)); cubeCam.lookAt(0, 0, 0); cubeRenderer.render(cubeScene, cubeCam); }
(function loop() { controls.update(); renderer.render(scene, activeCam()); renderCube(); requestAnimationFrame(loop); })();

// ---- markers (violations)
function setMarkers(violations) {
  markerGroup.clear();
  const col = { error: 0xef5a5a, warn: 0xf2a93b, info: 0x5aa5ef };
  violations.forEach((v, i) => { if (!v.location) return; const s = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.6, S.size * 0.012), 12, 12), new THREE.MeshBasicMaterial({ color: col[v.severity] || 0xef5a5a, depthTest: false, transparent: true, opacity: 0.9 })); s.position.set(...v.location); s.renderOrder = 10; s.userData.i = i; markerGroup.add(s); });
}
function highlight(i) { markerGroup.children.forEach((m) => m.scale.setScalar(m.userData.i === i ? 2.2 : 1)); const v = S.violations[i]; if (v?.location) { controls.target.set(...v.location); controls.update(); } }

// ---- measure
function addMeasurePoint(p) {
  S.measurePts.push(p);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.5, S.size * 0.008)), new THREE.MeshBasicMaterial({ color: 0x5ad38a, depthTest: false })); dot.position.copy(p); dot.renderOrder = 11; selGroup.add(dot);
  if (S.measurePts.length === 2) {
    const [a, b] = S.measurePts; selGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0x5ad38a, depthTest: false })));
    S.measureText = `points: ${a.distanceTo(b).toFixed(2)} mm  (Δx ${Math.abs(a.x - b.x).toFixed(2)}, Δy ${Math.abs(a.y - b.y).toFixed(2)}, Δz ${Math.abs(a.z - b.z).toFixed(2)})`;
    S.measurePts = null; renderSelPanel(); status('measured');
  }
}
async function measureSelection() {
  if (!S.selection.length) { S.measurePts = []; selGroup.clear(); S.measureText = ''; renderSelPanel(); status('measure: click two points on the part (Esc to stop)'); return; }
  const items = S.selection.filter((s) => s.kind !== 'bodies').slice(0, 2).map((s) => ({ kind: s.kind, index: s.index }));
  try {
    const r = await api('/api/measure', { name: S.part, params: S.params, items });
    if (r.distance != null) S.measureText = `min distance ${r.distance} mm · centre-to-centre ${r.center_distance} mm (Δ ${r.center_delta.join(', ')})` + (r.angle != null ? ` · angle ${r.angle}°` : '');
    else if (r.info) S.measureText = Object.entries(r.info).filter(([k]) => !['id', 'bbox', 'tri_start', 'tri_count', 'body'].includes(k)).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ');
    renderSelPanel();
  } catch (e) { status(e.message, true); }
}

// ================================================================ browser tree
function renderTree() {
  const t = $('tree'); if (!S.topo) { t.innerHTML = ''; return; }
  const bodies = S.topo.bodies.map((b) => { const sel = S.selection.some((s) => s.kind === 'bodies' && s.index === b.id); const hidden = S.hiddenBodies.has(b.id); return `<div class="node ${sel ? 'sel' : ''}" data-body="${b.id}"><span class="eye ${hidden ? 'off' : ''}" data-eye="${b.id}">👁</span><span>${esc(b.label)}</span><small style="color:var(--muted)">${b.faces} faces</small></div>`; }).join('');
  const planes = ['XY', 'XZ', 'YZ'].map((n) => { const vis = planeGroup.getObjectByName(n)?.visible; return `<div class="node sub"><span class="eye ${vis ? '' : 'off'}" data-plane="${n}">👁</span><span>${n} plane</span></div>`; }).join('');
  t.innerHTML = `<div class="node" style="color:var(--muted)">Bodies</div>${bodies}<div class="node" style="color:var(--muted)">Origin</div>${planes}`;
  t.querySelectorAll('[data-eye]').forEach((el) => (el.onclick = (e) => { e.stopPropagation(); const id = +el.dataset.eye; if (S.hiddenBodies.has(id)) S.hiddenBodies.delete(id); else S.hiddenBodies.add(id); group.children.forEach((m) => (m.visible = !S.hiddenBodies.has(m.userData.body))); renderTree(); }));
  t.querySelectorAll('[data-plane]').forEach((el) => (el.onclick = () => { const n = el.dataset.plane; const p = planeGroup.getObjectByName(n), pe = planeGroup.getObjectByName(n + '_e'); p.visible = pe.visible = !p.visible; renderTree(); }));
  t.querySelectorAll('[data-body]').forEach((el) => (el.onclick = () => { S.selection = [{ kind: 'bodies', index: +el.dataset.body }]; paintSelection(); }));
}

// ================================================================ toolbar, context menu, palette
const GROUPS = ['Create', 'Modify', 'Pattern', 'Construct', 'Inspect'];
const EXTRA = { _measure: { label: 'Measure', key: 'I' }, _orient: { label: 'Print orientation' }, _section: { label: 'Section analysis' }, _isolate: { label: 'Isolate body / show all' }, _fit: { label: 'Fit view', key: 'F6' }, _palette: { label: 'All commands…', key: 'S' } };
function cmdLabel(id) { const c = S.commands.find((x) => x.id === id); return c ? { label: c.label, key: c.key } : EXTRA[id] || { label: id }; }
function buildToolbar() {
  const tb = $('toolbar'); tb.querySelectorAll('.grp').forEach((e) => e.remove());
  const spacer = tb.querySelector('.spacer');
  for (const g of GROUPS) {
    const ids = S.commands.filter((c) => c.group === g).map((c) => c.id);
    if (g === 'Inspect') ids.push('_measure', '_orient', '_section');
    if (!ids.length) continue;
    const d = document.createElement('div'); d.className = 'grp';
    d.innerHTML = `<button>${g} ▾</button><div class="menu">${ids.map((id) => { const l = cmdLabel(id); return `<div class="item" data-cmd="${id}"><span>${esc(l.label)}</span>${l.key ? `<kbd>${l.key}</kbd>` : ''}</div>`; }).join('')}</div>`;
    d.querySelector('button').onclick = (e) => { e.stopPropagation(); const open = d.classList.contains('open'); closeMenus(); if (!open) d.classList.add('open'); };
    d.querySelectorAll('.item').forEach((it) => (it.onclick = () => { closeMenus(); runCommand(it.dataset.cmd); }));
    tb.insertBefore(d, spacer);
  }
}
function closeMenus() { document.querySelectorAll('.toolbar .grp.open').forEach((g) => g.classList.remove('open')); $('ctx').classList.remove('show'); }
document.addEventListener('click', closeMenus);
document.querySelectorAll('[data-filter]').forEach((b) => (b.onclick = () => { document.querySelectorAll('[data-filter]').forEach((x) => x.classList.remove('active')); b.classList.add('active'); S.filter = b.dataset.filter; }));

function showCtx(e) {
  const kinds = new Set(S.selection.map((s) => s.kind));
  let ids;
  if (kinds.has('faces')) ids = ['extrude', 'hole', 'text', 'pattern_rect', 'pattern_circ', 'shell', 'plane_face', '_measure'];
  else if (kinds.has('edges')) ids = ['fillet', 'chamfer', '_measure'];
  else if (kinds.has('bodies')) ids = ['move', 'scale', 'mirror', 'split', '_isolate'];
  else ids = ['box', 'cylinder', 'sphere', 'extrude', 'hole', '_fit', '_palette'];
  const ctx = $('ctx');
  ctx.innerHTML = ids.map((id) => { const l = cmdLabel(id); return `<div class="item" data-cmd="${id}"><span>${esc(l.label)}</span>${l.key ? `<kbd>${l.key}</kbd>` : ''}</div>`; }).join('');
  ctx.style.left = Math.min(e.clientX, innerWidth - 220) + 'px'; ctx.style.top = Math.min(e.clientY, innerHeight - 300) + 'px'; ctx.classList.add('show');
  ctx.querySelectorAll('.item').forEach((it) => (it.onclick = (ev) => { ev.stopPropagation(); closeMenus(); runCommand(it.dataset.cmd); }));
}

function paletteItems() {
  const items = S.commands.map((c) => ({ id: c.id, label: `${c.group}: ${c.label}`, key: c.key }));
  items.push({ id: '_measure', label: 'Inspect: Measure', key: 'I' }, { id: '_orient', label: 'Inspect: Print orientation' }, { id: '_section', label: 'Inspect: Section analysis' },
    { id: '_fit', label: 'View: Fit', key: 'F6' }, { id: '_view_iso', label: 'View: Home (iso)' }, { id: '_view_front', label: 'View: Front' }, { id: '_view_back', label: 'View: Back' }, { id: '_view_top', label: 'View: Top' }, { id: '_view_bottom', label: 'View: Bottom' }, { id: '_view_right', label: 'View: Right' }, { id: '_view_left', label: 'View: Left' },
    { id: '_isolate', label: 'Display: Isolate selected body / show all' }, { id: '_export', label: 'File: Export…' }, { id: '_undo', label: 'Edit: Undo', key: 'Ctrl+Z' }, { id: '_redo', label: 'Edit: Redo', key: 'Ctrl+Y' },
    { id: '_newpart', label: 'File: New part' }, { id: '_guide', label: 'Help: Guide' });
  return items;
}
function openPalette() { $('palette').classList.add('show'); $('palInput').value = ''; renderPalette(''); $('palInput').focus(); }
function renderPalette(q) {
  const ql = q.toLowerCase().split(/\s+/).filter(Boolean);
  const items = paletteItems().filter((it) => ql.every((w) => it.label.toLowerCase().includes(w)));
  $('palList').innerHTML = items.slice(0, 16).map((it, i) => `<div class="item ${i === 0 ? 'hi' : ''}" data-cmd="${it.id}"><span>${esc(it.label)}</span>${it.key ? `<kbd>${it.key}</kbd>` : ''}</div>`).join('') || '<div class="item" style="color:var(--muted)">no match</div>';
  $('palList').querySelectorAll('.item[data-cmd]').forEach((it) => (it.onclick = () => { $('palette').classList.remove('show'); runCommand(it.dataset.cmd); }));
}
$('palInput').addEventListener('input', () => renderPalette($('palInput').value));
$('palInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { $('palList').querySelector('.item.hi[data-cmd]')?.click(); }
  else if (e.key === 'Escape') $('palette').classList.remove('show');
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { const all = [...$('palList').querySelectorAll('.item[data-cmd]')]; const i = all.findIndex((x) => x.classList.contains('hi')); all.forEach((x) => x.classList.remove('hi')); all[(i + (e.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length]?.classList.add('hi'); e.preventDefault(); }
});
$('btnPalette').onclick = (e) => { e.stopPropagation(); openPalette(); };

async function runCommand(id) {
  if (id.startsWith('_')) {
    if (id === '_measure') return measureSelection();
    if (id === '_orient') return $('btnOrient').click();
    if (id === '_fit') return fitKeep();
    if (id.startsWith('_view_')) return fitView(id.slice(6));
    if (id === '_isolate') { const b = S.selection.find((s) => s.kind === 'bodies'); if (b && !S.hiddenBodies.size) S.topo.bodies.forEach((x) => { if (x.id !== b.index) S.hiddenBodies.add(x.id); }); else S.hiddenBodies.clear(); group.children.forEach((m) => (m.visible = !S.hiddenBodies.has(m.userData.body))); renderTree(); return; }
    if (id === '_export') return $('btnExport').click();
    if (id === '_undo') return undoRedo('undo');
    if (id === '_redo') return undoRedo('redo');
    if (id === '_newpart') return $('btnNew').click();
    if (id === '_guide') return $('btnGuide').click();
    if (id === '_section') { $('secAxis').value = $('secAxis').value ? '' : 'y'; updateClip(); return; }
    if (id === '_palette') return openPalette();
    return;
  }
  const cmd = S.commands.find((c) => c.id === id); if (!cmd || !S.part) return;
  openDialog(cmd);
}

// ================================================================ command dialog (writes code)
function openDialog(cmd) {
  if (S.dialog) closeDialog(false);
  const values = {}; for (const f of cmd.fields) values[f.name] = f.kind === 'selection' ? [] : f.default;
  for (const f of cmd.fields) if (f.kind === 'selection') { const sel = S.selection.filter((s) => s.kind === f.select && s.expr); if (sel.length) { values[f.name] = (f.multi ? sel : sel.slice(0, 1)).map((s) => s.expr); break; } }
  S.dialog = { cmd, values, activeField: null, code: null };
  renderDialog(); previewDialog();
}
function shortExpr(e) { return e.replace(/^\w+\./, '').replace('faces()', 'F').replace('edges()', 'E').replace(/sort_by/g, 'by').replace(/filter_by/g, 'of').replace('GeomType.', '').replace(/Axis\./g, ''); }
function renderDialog() {
  const d = $('dialog'); const { cmd, values } = S.dialog;
  const html = cmd.fields.map((f) => {
    if (f.kind === 'selection') return `<div class="f selection"><label>${esc(f.label)} <span style="font-size:10px">(${f.select}${f.multi ? ', shift-click for several' : ''})</span></label><div class="chips ${S.dialog.activeField === f ? 'active' : ''}" data-field="${f.name}">${(values[f.name] || []).map((e) => `<span class="chip">${esc(shortExpr(e))}</span>`).join('') || '<span style="color:var(--muted);font-size:11px">click here, then pick in the viewer</span>'}</div></div>`;
    if (f.kind === 'choice') return `<div class="f"><label>${esc(f.label)}</label><select data-field="${f.name}">${f.choices.map((c) => `<option ${c === values[f.name] ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></div>`;
    if (f.kind === 'bool') return `<div class="f"><label>${esc(f.label)}</label><input type="checkbox" data-field="${f.name}" ${values[f.name] ? 'checked' : ''}></div>`;
    if (f.kind === 'text') return `<div class="f"><label>${esc(f.label)}</label><input type="text" data-field="${f.name}" value="${esc(values[f.name] ?? '')}"></div>`;
    return `<div class="f"><label>${esc(f.label)}${f.unit ? ` <span style="font-size:10px">${esc(f.unit)}</span>` : ''}</label><input type="number" data-field="${f.name}" value="${values[f.name] ?? ''}" ${f.step ? `step="${f.step}"` : ''} ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''}></div>`;
  }).join('');
  d.innerHTML = `<div class="head"><span>${esc(cmd.label)}</span><button data-close>✕</button></div><div class="body">${cmd.doc ? `<div style="color:var(--muted);font-size:11px">${esc(cmd.doc)}</div>` : ''}${html}<div class="pv" id="dlgPv">…</div></div><div class="foot"><span id="dlgInfo" style="font-size:11px;color:var(--muted)"></span><span><button data-cancel>Cancel</button> <button class="primary" data-ok>OK</button></span></div>`;
  d.classList.add('show');
  d.querySelector('[data-close]').onclick = () => closeDialog(true); d.querySelector('[data-cancel]').onclick = () => closeDialog(true);
  d.querySelector('[data-ok]').onclick = applyDialog;
  d.querySelectorAll('input,select').forEach((el) => { const f = cmd.fields.find((x) => x.name === el.dataset.field); const h = () => { values[f.name] = f.kind === 'bool' ? el.checked : f.kind === 'number' ? +el.value : el.value; previewDialog(); }; el.oninput = h; el.onchange = h; });
  d.querySelectorAll('.chips').forEach((el) => (el.onclick = () => { const f = cmd.fields.find((x) => x.name === el.dataset.field); S.dialog.activeField = S.dialog.activeField === f ? null : f; S.selection = []; paintSelection(); renderDialog(); status(S.dialog.activeField ? `pick ${f.select} in the viewer for "${f.label}"` : 'ready'); }));
}
function dialogTakeSelection() {
  const f = S.dialog.activeField; const exprs = S.selection.filter((s) => s.kind === f.select && s.expr).map((s) => s.expr);
  S.dialog.values[f.name] = f.multi ? exprs : exprs.slice(-1);
  if (!f.multi) S.dialog.activeField = null;
  renderDialog(); previewDialog();
}
let pvTimer = null;
function previewDialog() {
  clearTimeout(pvTimer);
  pvTimer = setTimeout(async () => {
    if (!S.dialog) return;
    const { cmd, values } = S.dialog;
    try {
      const r = await api('/api/command/preview', { name: S.part, params: S.params, cmd: cmd.id, values });
      if (!S.dialog) return;
      S.dialog.code = r.code;
      const pv = $('dlgPv');
      if (r.ok) { setTopo(r.topo, { preview: true }); const ne = r.violations.filter((v) => v.severity === 'error').length, nw = r.violations.filter((v) => v.severity === 'warn').length; pv.className = 'pv ' + (ne ? 'bad' : 'ok'); pv.textContent = r.code + `\n— preview OK: ${ne ? ne + ' error(s), ' : ''}${nw} warning(s)`; $('dlgInfo').textContent = r.report.size.map((x) => x.toFixed(1)).join(' × ') + ' mm'; }
      else { pv.className = 'pv bad'; pv.textContent = r.code + '\n— ' + (r.error || 'failed') + '\n' + (r.detail || ''); $('dlgInfo').textContent = ''; }
    } catch (e) { if (S.dialog) { $('dlgPv').className = 'pv bad'; $('dlgPv').textContent = e.message; } }
  }, 350);
}
async function applyDialog() {
  if (!S.dialog) return;
  const { cmd, values, code } = S.dialog;
  try {
    const r = await api('/api/command/apply', { name: S.part, params: S.params, cmd: cmd.id, values, code });
    S.dialog = null; $('dialog').classList.remove('show');
    S.source = r.source; cm.setValue(r.source); S.dirty = false; $('editorStatus').textContent = ''; S.schema = r.schema; renderParams(true);
    markNew(r.lines[0], r.lines[1]);
    S.selection = []; await build();
    status(`${cmd.label} added at lines ${r.lines[0]}–${r.lines[1]}`);
  } catch (e) { showError(e); }
}
function closeDialog(rebuild) { if (!S.dialog) return; S.dialog = null; $('dialog').classList.remove('show'); clearTimeout(pvTimer); if (rebuild) build(); }

// ================================================================ editor
const cm = CodeMirror.fromTextArea($('code'), { mode: 'python', theme: 'material-darker', lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false, extraKeys: { 'Ctrl-Enter': saveAndBuild, 'Cmd-Enter': saveAndBuild, Tab: (c) => c.execCommand('indentMore'), 'Shift-Tab': (c) => c.execCommand('indentLess') } });
cm.on('change', () => { S.dirty = cm.getValue() !== S.source; $('editorStatus').textContent = S.dirty ? 'unsaved changes' : ''; });
$('btnToggleEditor').onclick = () => { $('editorWrap').classList.toggle('collapsed'); setTimeout(() => cm.refresh(), 50); };
$('btnRevert').onclick = () => cm.setValue(S.source);
$('btnSaveBuild').onclick = saveAndBuild;
let errMark = null, newMarks = [];
function markError(line) { if (errMark != null) { cm.removeLineClass(errMark, 'background', 'cm-errline'); errMark = null; } if (line) { errMark = line - 1; cm.addLineClass(errMark, 'background', 'cm-errline'); cm.scrollIntoView({ line: errMark, ch: 0 }, 60); } }
function markNew(a, b) { newMarks.forEach((l) => cm.removeLineClass(l, 'background', 'cm-newline')); newMarks = []; for (let l = a - 1; l < b; l++) { cm.addLineClass(l, 'background', 'cm-newline'); newMarks.push(l); } cm.scrollIntoView({ line: b - 1, ch: 0 }, 60); setTimeout(() => { newMarks.forEach((l) => cm.removeLineClass(l, 'background', 'cm-newline')); newMarks = []; }, 4000); }
async function saveAndBuild() {
  if (!S.part) return;
  try { status('saving…'); const r = await api(`/api/part/${S.part}/source`, { source: cm.getValue() }); S.source = cm.getValue(); S.dirty = false; $('editorStatus').textContent = ''; markError(null); S.schema = r.schema; renderParams(true); await build(); } catch (e) { showError(e); }
}
function showError(e) { status(e.message, true); $('report').textContent = (e.message || '') + '\n' + (e.detail || ''); $('checks').innerHTML = `<div class="err">${esc(e.message)}\n${esc(e.detail || '')}</div>`; if (e.line) markError(e.line); }

// ================================================================ params
function renderParams(keepValues) {
  const box = $('params'); box.innerHTML = '';
  const specs = (S.schema && S.schema.params) || [];
  $('procLabel').textContent = (S.schema && S.schema.process) || '';
  const next = {}; const oldDefaults = S.defaults || {};
  for (const sp of specs) {
    const defaultChanged = sp.name in oldDefaults && oldDefaults[sp.name] !== sp.default;
    next[sp.name] = keepValues && sp.name in S.params && !defaultChanged ? S.params[sp.name] : sp.default;
    const row = document.createElement('div'); row.className = 'param' + (sp.kind === 'bool' ? ' bool' : '');
    const lab = document.createElement('label'); lab.innerHTML = `${sp.name}${sp.unit ? ` <span class="doc">(${sp.unit})</span>` : ''}<div class="doc">${esc(sp.doc || '')}</div>`; row.appendChild(lab);
    if (sp.kind === 'bool') { const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !!next[sp.name]; cb.onchange = () => setParam(sp.name, cb.checked); row.appendChild(cb); }
    else if (sp.kind === 'choice') { const sel = document.createElement('select'); for (const c of sp.choices) { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); } sel.value = next[sp.name]; sel.onchange = () => setParam(sp.name, sel.value); row.appendChild(sel); }
    else if (sp.kind === 'str') { const inp = document.createElement('input'); inp.type = 'text'; inp.value = next[sp.name]; inp.onchange = () => setParam(sp.name, inp.value); row.appendChild(inp); }
    else {
      const num = document.createElement('input'); num.type = 'number'; num.value = next[sp.name]; if (sp.step) num.step = sp.step; if (sp.min != null) num.min = sp.min; if (sp.max != null) num.max = sp.max; row.appendChild(num);
      if (sp.min != null && sp.max != null) { const rng = document.createElement('input'); rng.type = 'range'; rng.min = sp.min; rng.max = sp.max; rng.step = sp.step || (sp.kind === 'int' ? 1 : (sp.max - sp.min) / 200); rng.value = next[sp.name]; rng.oninput = () => { num.value = rng.value; setParam(sp.name, +rng.value, true); }; num.oninput = () => { rng.value = num.value; setParam(sp.name, +num.value, true); }; row.appendChild(rng); }
      else num.oninput = () => setParam(sp.name, +num.value, true);
    }
    box.appendChild(row);
  }
  S.params = next; S.defaults = Object.fromEntries(specs.map((sp) => [sp.name, sp.default]));
}
function setParam(name, value, debounce) { S.params[name] = value; clearTimeout(S.buildTimer); S.buildTimer = setTimeout(build, debounce ? 250 : 0); }
$('btnReset').onclick = () => { renderParams(false); build(); };
$('btnRebuild').onclick = () => build();

// ================================================================ build
async function build() {
  if (!S.part) return;
  if (S.building) { S.queued = true; return; }
  S.building = true; status('building…');
  try {
    const t0 = performance.now();
    const r = await api('/api/build', { name: S.part, params: S.params });
    S.violations = r.violations;
    S.selection.forEach((s) => { delete s.expr; });
    setTopo(r.topo);
    if (!S.hasFit) { fitView('iso'); makePlanes(); S.hasFit = true; }
    setMarkers(r.violations); renderChecks(r.violations);
    $('report').textContent = r.summary.split('\nchecks:')[0];
    const sz = r.report.size.map((x) => x.toFixed(1)).join(' × ');
    $('hud').innerHTML = `<span class="pill">${sz} mm</span><span class="pill">${Math.round(r.report.volume).toLocaleString()} mm³${r.report.mass_g ? ` · ${r.report.mass_g.toFixed(1)} g` : ''}</span><span class="pill">${r.report.n_solids} body · ${r.report.n_faces} faces</span>`;
    status(`built in ${r.build_seconds.toFixed(2)}s (round trip ${((performance.now() - t0) / 1000).toFixed(2)}s) · ${r.param_hash}`);
    markError(null);
    await resolveSelectors();
  } catch (e) { showError(e); }
  S.building = false;
  if (S.queued) { S.queued = false; build(); }
}
function renderChecks(vs) {
  const box = $('checks'); box.innerHTML = '';
  const ne = vs.filter((v) => v.severity === 'error').length, nw = vs.filter((v) => v.severity === 'warn').length;
  $('checkCount').innerHTML = ne ? `<span style="color:var(--err)">${ne} error</span> · ${nw} warn` : nw ? `<span style="color:var(--warn)">${nw} warn</span>` : `<span style="color:var(--ok)">clean</span>`;
  vs.forEach((v, i) => { const d = document.createElement('div'); d.className = `v ${v.severity}`; d.innerHTML = `<b>${v.rule}</b> ${esc(v.message)}${v.fix ? `<div class="fix">→ ${esc(v.fix)}</div>` : ''}`; d.onclick = () => highlight(i); box.appendChild(d); });
  if (!vs.length) box.innerHTML = '<div class="v info">No issues found.</div>';
}

// ================================================================ projects / parts
async function loadProjects() {
  const r = await api('/api/projects');
  const sel = $('projectSel'); sel.innerHTML = '';
  for (const p of r.projects) { const o = document.createElement('option'); o.value = p.name; o.textContent = `${p.name} (${p.parts})`; sel.appendChild(o); }
  if (!r.projects.length) { const o = document.createElement('option'); o.textContent = '(no projects — click +)'; sel.appendChild(o); }
  if (!S.project || !r.projects.some((p) => p.name === S.project)) S.project = r.active;
  sel.value = S.project;
}
$('projectSel').onchange = async () => { if (S.dirty && !confirm('Discard unsaved code changes?')) { $('projectSel').value = S.project; return; } S.project = $('projectSel').value; S.part = null; await loadParts(); };
$('btnNewProject').onclick = () => { $('projName').value = ''; $('modalProject').classList.add('open'); $('projName').focus(); };
$('projCancel').onclick = () => $('modalProject').classList.remove('open');
$('projCreate').onclick = async () => { const name = $('projName').value.trim(); if (!name) return; try { const r = await api('/api/projects/new', { name, starter: 'blank', part: 'part1' }); $('modalProject').classList.remove('open'); S.project = r.active; S.part = null; await loadProjects(); await loadParts(r.part); } catch (e) { alert(e.message); } };
$('projName').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('projCreate').click(); });

async function loadParts(select) {
  const r = await api('/api/parts');
  $('project').textContent = r.project;
  const box = $('parts'); box.innerHTML = '';
  for (const p of r.parts) { const a = document.createElement('a'); a.className = p.name === S.part ? 'active' : ''; a.innerHTML = `${p.name}<small>${esc(p.doc || '')}</small>`; a.onclick = () => openPart(p.name); box.appendChild(a); }
  if (select) openPart(select); else if (!S.part && r.parts.length) openPart(r.parts[0].name);
}
async function openPart(name) {
  if (S.dirty && !confirm('Discard unsaved code changes?')) return;
  closeDialog(false);
  S.part = name; S.hasFit = false; S.dirty = false; S.selection = []; S.hiddenBodies = new Set(); selGroup.clear(); S.measureText = ''; S.measurePts = null;
  document.querySelectorAll('.parts a').forEach((a) => a.classList.toggle('active', a.firstChild.textContent === name));
  try { const r = await api(`/api/part/${name}`); S.source = r.source; cm.setValue(r.source); S.schema = r.schema; renderParams(false); if (r.schema.error) { showError({ message: r.schema.error, detail: r.schema.detail, line: r.schema.line }); return; } await build(); } catch (e) { showError(e); }
}
$('btnRefresh').onclick = () => loadParts();
$('btnNew').onclick = async () => { const st = await api('/api/starters'); const box = $('starters'); box.innerHTML = ''; S.starter = 'blank'; for (const s of st) { const d = document.createElement('div'); d.className = 'starter' + (s.name === 'blank' ? ' sel' : ''); d.innerHTML = `<b>${s.name}</b><div style="color:var(--muted)">${esc(s.doc)}</div>`; d.onclick = () => { S.starter = s.name; box.querySelectorAll('.starter').forEach((x) => x.classList.remove('sel')); d.classList.add('sel'); }; box.appendChild(d); } $('modalNew').classList.add('open'); $('newName').focus(); };
$('newCancel').onclick = () => $('modalNew').classList.remove('open');
$('newCreate').onclick = async () => { const name = $('newName').value.trim().replace(/[^\w-]/g, '_'); if (!name) return; try { const r = await api('/api/new', { name, starter: S.starter }); $('modalNew').classList.remove('open'); await loadParts(r.name); } catch (e) { alert(e.message); } };
$('newName').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('newCreate').click(); });

async function undoRedo(which) { if (!S.part) return; try { await api(`/api/${which}`, { name: S.part }); const r = await api(`/api/part/${S.part}`); S.source = r.source; cm.setValue(r.source); S.dirty = false; S.schema = r.schema; renderParams(true); await build(); status(which); } catch (e) { status(e.message, true); } }
$('btnUndo').onclick = () => undoRedo('undo'); $('btnRedo').onclick = () => undoRedo('redo');

// export / orient / guide / settings
$('btnExport').onclick = () => { $('exportResult').innerHTML = ''; $('modalExport').classList.add('open'); };
$('exportClose').onclick = () => $('modalExport').classList.remove('open');
document.querySelectorAll('#modalExport [data-fmt]').forEach((b) => (b.onclick = async () => { b.disabled = true; try { const r = await api('/api/export', { name: S.part, params: S.params, formats: [b.dataset.fmt] }); for (const f of Object.values(r.files)) $('exportResult').innerHTML += `<div>✓ <a href="/out/${encodeURIComponent(f)}?project=${encodeURIComponent(S.project)}" style="color:var(--accent)">${f}</a></div>`; } catch (e) { $('exportResult').innerHTML += `<div class="err">${esc(e.message)}</div>`; } b.disabled = false; }));
$('btnOrient').onclick = async () => { status('ranking orientations…'); try { const r = await api('/api/orient', { name: S.part, params: S.params }); $('modalTextBody').innerHTML = `<h3 style="margin-top:0">Print orientation</h3><pre>${esc(r.text)}</pre>`; $('modalText').classList.add('open'); status('ready'); } catch (e) { showError(e); } };
$('btnGuide').onclick = async () => { const t = await (await fetch('/api/guide')).text(); $('modalTextBody').innerHTML = marked.parse(t); $('modalText').classList.add('open'); };
$('textClose').onclick = () => $('modalText').classList.remove('open');
document.querySelectorAll('.modal').forEach((m) => m.addEventListener('click', (e) => { if (e.target === m) m.classList.remove('open'); }));
async function loadSettings() { const r = await api('/api/settings'); $('aiModel').textContent = r.has_key ? r.model : 'no API key — ⚙'; $('keyHint').textContent = r.has_key ? `(saved: ${r.key_hint})` : '(none saved)'; const sel = $('modelSel'); sel.innerHTML = ''; for (const m of r.models) { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); } sel.value = r.model; return r; }
$('btnSettings').onclick = async () => { await loadSettings(); $('apiKey').value = ''; $('modalSettings').classList.add('open'); };
$('settingsCancel').onclick = () => $('modalSettings').classList.remove('open');
$('settingsSave').onclick = async () => { await api('/api/settings', { api_key: $('apiKey').value, model: $('modelSel').value }); $('modalSettings').classList.remove('open'); await loadSettings(); };
$('keyClear').onclick = async () => { await api('/api/settings', { clear_key: true }); await loadSettings(); $('apiKey').value = ''; };

// AI
function aiMsg(text, cls = '') { const d = document.createElement('div'); d.className = 'msg ' + cls; d.textContent = text; $('aiLog').appendChild(d); $('aiLog').scrollTop = 1e9; return d; }
async function aiSend() {
  const prompt = $('aiPrompt').value.trim(); if (!prompt || !S.part) return;
  if (S.dirty) { if (!confirm('Save your code changes first?')) return; await saveAndBuild(); }
  const st = await loadSettings(); if (!st.has_key) { $('btnSettings').click(); return; }
  $('aiSend').disabled = true; $('aiStatus').textContent = 'thinking…'; aiMsg('▶ ' + prompt, 'ok'); $('aiPrompt').value = '';
  try {
    const { id } = await api('/api/ai', { name: S.part, prompt }); let since = 0, builds = 0;
    while (true) {
      await sleep(1200); const j = await api(`/api/ai/${id}?since=${since}`); since = j.next;
      for (const ev of j.events) { if (ev.kind === 'text') aiMsg(ev.text); else if (ev.kind === 'tool') aiMsg('⚙ ' + ev.summary, 'tool'); else if (ev.kind === 'build') { builds++; aiMsg(`build ${builds}: ${ev.ok ? 'clean' : 'has errors'} — ${ev.summary.split('\n').find((l) => l.startsWith('checks:')) || ''}`, 'tool'); } }
      if (j.changed) $('aiStatus').textContent = `working… (${builds} builds)`;
      if (j.done) { if (j.error) aiMsg('✗ ' + j.error, 'bad'); break; }
    }
    const r = await api(`/api/part/${S.part}`); S.source = r.source; cm.setValue(r.source); S.dirty = false; S.schema = r.schema; renderParams(true); await build();
  } catch (e) { aiMsg('✗ ' + e.message, 'bad'); }
  $('aiSend').disabled = false; $('aiStatus').textContent = '';
}
$('aiSend').onclick = aiSend;
$('aiPrompt').addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') aiSend(); });

// ================================================================ keyboard shortcuts (Fusion-style)
document.addEventListener('keydown', (e) => {
  const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || !!document.activeElement?.closest?.('.CodeMirror');
  if (e.key === 'Escape') { if ($('palette').classList.contains('show')) $('palette').classList.remove('show'); else if (S.dialog) closeDialog(true); else { S.selection = []; S.measurePts = null; S.measureText = ''; selGroup.clear(); paintSelection(); } return; }
  if (inField) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undoRedo(e.shiftKey ? 'redo' : 'undo'); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); undoRedo('redo'); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'F6') { e.preventDefault(); fitKeep(); return; }
  const map = { s: '_palette', e: 'extrude', q: 'extrude', h: 'hole', f: 'fillet', c: 'chamfer', m: 'move', i: '_measure', b: 'box' };
  const id = map[e.key.toLowerCase()];
  if (id) { e.preventDefault(); runCommand(id); }
});

// ================================================================ boot
(async () => {
  try { S.commands = await api('/api/commands'); } catch (e) { S.commands = []; }
  buildToolbar();
  await loadProjects(); await loadParts(); loadSettings();
})();
