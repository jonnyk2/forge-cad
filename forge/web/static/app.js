import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ---------------------------------------------------------------- state
const S = {
  part: null, schema: null, params: {}, source: '', dirty: false,
  mesh: null, edges: null, markers: [], bbox: null, violations: [],
  measuring: false, measurePts: [], buildTimer: null, building: false, queued: false,
};
const $ = (id) => document.getElementById(id);
const status = (t, bad = false) => { $('status').textContent = t; $('status').style.color = bad ? 'var(--err)' : 'var(--muted)'; };
const api = async (url, body) => {
  const r = await fetch(url, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), j);
  return j;
};

// ---------------------------------------------------------------- three.js
const viewer = $('viewer');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.localClippingEnabled = true;
viewer.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x404060, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(80, -120, 160); scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(-100, 80, 40); scene.add(fill);
const grid = new THREE.GridHelper(400, 40, 0x3a4150, 0x262b33); grid.rotation.x = Math.PI / 2; scene.add(grid);
const axes = new THREE.AxesHelper(20); scene.add(axes);
const clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e9);
const matBody = new THREE.MeshStandardMaterial({ color: 0xc9cdd6, metalness: 0.05, roughness: 0.55, side: THREE.DoubleSide, clippingPlanes: [clipPlane], clipShadows: true });
const matOver = new THREE.MeshStandardMaterial({ color: 0xef6a4a, metalness: 0.05, roughness: 0.6, side: THREE.DoubleSide, clippingPlanes: [clipPlane], transparent: true, opacity: 0.95 });
const matEdge = new THREE.LineBasicMaterial({ color: 0x1b1e24, clippingPlanes: [clipPlane] });
const group = new THREE.Group(); scene.add(group);
const markerGroup = new THREE.Group(); scene.add(markerGroup);
const measureGroup = new THREE.Group(); scene.add(measureGroup);

function resize() {
  const w = viewer.clientWidth, h = viewer.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewer); resize();
(function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();

function fitView(name = 'iso') {
  if (!S.bbox) return;
  const [mn, mx] = S.bbox;
  const c = new THREE.Vector3((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2);
  const size = Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]);
  const d = size * 1.9 + 10;
  const dir = { iso: [1, -1.2, 0.9], front: [0, -1, 0.0001], top: [0, 0.0001, 1], right: [1, 0, 0.0001] }[name];
  const v = new THREE.Vector3(...dir).normalize().multiplyScalar(d);
  camera.position.copy(c.clone().add(v)); controls.target.copy(c); controls.update();
  grid.position.set(c.x, c.y, mn[2] - 0.05);
  const g = Math.pow(10, Math.floor(Math.log10(size * 3)));
  grid.scale.setScalar((size * 3) / 400 * (400 / (g * 4)) || 1);
}

function setMesh(mesh, edges, overhangLimit) {
  group.clear();
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(mesh.vertices);
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setIndex(mesh.indices);
  geo.computeVertexNormals();
  // split overhang triangles into a second material group by colouring per-face
  const nonIdx = geo.toNonIndexed();
  const p = nonIdx.attributes.position.array;
  const n = p.length / 9;
  const groupsA = [], groupsB = [];
  const zmin = mesh.bbox[0][2];
  const lim = Math.sin((overhangLimit || 45) * Math.PI / 180);
  const idxA = [], idxB = [];
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), nn = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    a.fromArray(p, i * 9); b.fromArray(p, i * 9 + 3); c.fromArray(p, i * 9 + 6);
    nn.copy(b).sub(a).cross(c.clone().sub(a)).normalize();
    const onBed = Math.max(a.z, b.z, c.z) < zmin + 1e-3;
    const over = nn.z < -1e-3 && (-nn.z) > lim && !onBed;
    (over ? idxB : idxA).push(i * 3, i * 3 + 1, i * 3 + 2);
  }
  const mk = (idx, mat) => { if (!idx.length) return; const g2 = new THREE.BufferGeometry(); g2.setAttribute('position', nonIdx.attributes.position); g2.setIndex(idx); g2.computeVertexNormals(); group.add(new THREE.Mesh(g2, mat)); };
  mk(idxA, matBody); mk(idxB, matOver);
  if (edges) {
    const segs = [];
    for (const poly of edges) for (let i = 0; i + 5 < poly.length; i += 3) segs.push(poly[i], poly[i + 1], poly[i + 2], poly[i + 3], poly[i + 4], poly[i + 5]);
    const eg = new THREE.BufferGeometry(); eg.setAttribute('position', new THREE.Float32BufferAttribute(segs, 3));
    const lines = new THREE.LineSegments(eg, matEdge); lines.name = 'edges'; lines.visible = S.edgesOn !== false; group.add(lines);
  }
  S.bbox = mesh.bbox;
  updateClip();
}

function setMarkers(violations) {
  markerGroup.clear();
  const col = { error: 0xef5a5a, warn: 0xf2a93b, info: 0x5aa5ef };
  violations.forEach((v, i) => {
    if (!v.location) return;
    const s = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.6, (S.size || 50) * 0.012), 12, 12), new THREE.MeshBasicMaterial({ color: col[v.severity] || 0xef5a5a, depthTest: false, transparent: true, opacity: 0.9 }));
    s.position.set(...v.location); s.renderOrder = 10; s.userData.i = i; markerGroup.add(s);
  });
}

function highlight(i) {
  markerGroup.children.forEach((m) => m.scale.setScalar(m.userData.i === i ? 2.2 : 1));
  const v = S.violations[i];
  if (v && v.location) { controls.target.set(...v.location); controls.update(); }
}

// section plane
function updateClip() {
  const ax = $('secAxis').value;
  if (!ax || !S.bbox) { clipPlane.constant = 1e9; return; }
  const i = { x: 0, y: 1, z: 2 }[ax];
  const t = $('secPos').value / 1000;
  const v = S.bbox[0][i] + (S.bbox[1][i] - S.bbox[0][i]) * t;
  const nrm = [0, 0, 0]; nrm[i] = -1;
  clipPlane.normal.set(...nrm); clipPlane.constant = v;
}
$('secAxis').onchange = updateClip; $('secPos').oninput = updateClip;
document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => fitView(b.dataset.view)));
$('btnEdges').onclick = () => { S.edgesOn = !(S.edgesOn !== false); const e = group.getObjectByName('edges'); if (e) e.visible = S.edgesOn; };

// measure: click two points on the surface
$('btnMeasure').onclick = () => { S.measuring = !S.measuring; S.measurePts = []; measureGroup.clear(); $('btnMeasure').style.borderColor = S.measuring ? 'var(--accent)' : ''; status(S.measuring ? 'measure: click two points on the part' : 'ready'); };
const ray = new THREE.Raycaster();
renderer.domElement.addEventListener('pointerdown', (e) => {
  if (!S.measuring) return;
  const r = renderer.domElement.getBoundingClientRect();
  const m = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(m, camera);
  const hits = ray.intersectObjects(group.children.filter((o) => o.isMesh));
  if (!hits.length) return;
  const p = hits[0].point;
  S.measurePts.push(p);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.5, (S.size || 50) * 0.008)), new THREE.MeshBasicMaterial({ color: 0x5ad38a, depthTest: false })); dot.position.copy(p); dot.renderOrder = 11; measureGroup.add(dot);
  if (S.measurePts.length === 2) {
    const [a, b] = S.measurePts;
    const g = new THREE.BufferGeometry().setFromPoints([a, b]);
    measureGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0x5ad38a, depthTest: false })));
    const d = a.distanceTo(b);
    status(`distance ${d.toFixed(2)} mm   Δx ${Math.abs(a.x - b.x).toFixed(2)}  Δy ${Math.abs(a.y - b.y).toFixed(2)}  Δz ${Math.abs(a.z - b.z).toFixed(2)}`);
    S.measurePts = [];
  }
});

// ---------------------------------------------------------------- editor
const cm = CodeMirror.fromTextArea($('code'), { mode: 'python', theme: 'material-darker', lineNumbers: true, indentUnit: 4, tabSize: 4, indentWithTabs: false, extraKeys: { 'Ctrl-Enter': saveAndBuild, 'Cmd-Enter': saveAndBuild, Tab: (c) => c.execCommand('indentMore'), 'Shift-Tab': (c) => c.execCommand('indentLess') } });
cm.on('change', () => { S.dirty = cm.getValue() !== S.source; $('editorStatus').textContent = S.dirty ? 'unsaved changes' : ''; });
$('btnToggleEditor').onclick = () => { $('editorWrap').classList.toggle('collapsed'); setTimeout(() => cm.refresh(), 50); };
$('btnRevert').onclick = () => { cm.setValue(S.source); };
$('btnSaveBuild').onclick = saveAndBuild;
let errMark = null;
function markError(line) { if (errMark) { cm.removeLineClass(errMark, 'background', 'cm-errline'); errMark = null; } if (line) { errMark = line - 1; cm.addLineClass(errMark, 'background', 'cm-errline'); cm.scrollIntoView({ line: errMark, ch: 0 }, 60); } }
const style = document.createElement('style'); style.textContent = '.cm-errline{background:rgba(239,90,90,.25)!important}'; document.head.appendChild(style);

async function saveAndBuild() {
  if (!S.part) return;
  try {
    status('saving…');
    const r = await api(`/api/part/${S.part}/source`, { source: cm.getValue() });
    S.source = cm.getValue(); S.dirty = false; $('editorStatus').textContent = ''; markError(null);
    S.schema = r.schema; renderParams(true);
    await build();
  } catch (e) { showError(e); }
}

function showError(e) {
  status(e.message, true);
  $('report').textContent = (e.message || '') + '\n' + (e.detail || '');
  $('checks').innerHTML = `<div class="err">${esc(e.message)}\n${esc(e.detail || '')}</div>`;
  if (e.line) markError(e.line);
}
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// ---------------------------------------------------------------- params
function renderParams(keepValues) {
  const box = $('params'); box.innerHTML = '';
  const specs = (S.schema && S.schema.params) || [];
  $('procLabel').textContent = (S.schema && S.schema.process) || '';
  const next = {};
  for (const sp of specs) {
    next[sp.name] = keepValues && sp.name in S.params ? S.params[sp.name] : sp.default;
    const row = document.createElement('div'); row.className = 'param' + (sp.kind === 'bool' ? ' bool' : '');
    const lab = document.createElement('label'); lab.innerHTML = `${sp.name}${sp.unit ? ` <span class="doc">(${sp.unit})</span>` : ''}<div class="doc">${esc(sp.doc || '')}</div>`;
    row.appendChild(lab);
    if (sp.kind === 'bool') {
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !!next[sp.name];
      cb.onchange = () => setParam(sp.name, cb.checked); row.appendChild(cb);
    } else if (sp.kind === 'choice') {
      const sel = document.createElement('select'); for (const c of sp.choices) { const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o); }
      sel.value = next[sp.name]; sel.onchange = () => setParam(sp.name, sel.value); row.appendChild(sel);
    } else if (sp.kind === 'str') {
      const inp = document.createElement('input'); inp.type = 'text'; inp.value = next[sp.name]; inp.onchange = () => setParam(sp.name, inp.value); row.appendChild(inp);
    } else {
      const num = document.createElement('input'); num.type = 'number'; num.value = next[sp.name];
      if (sp.step) num.step = sp.step; if (sp.min != null) num.min = sp.min; if (sp.max != null) num.max = sp.max;
      row.appendChild(num);
      if (sp.min != null && sp.max != null) {
        const rng = document.createElement('input'); rng.type = 'range'; rng.min = sp.min; rng.max = sp.max; rng.step = sp.step || (sp.kind === 'int' ? 1 : (sp.max - sp.min) / 200); rng.value = next[sp.name];
        rng.oninput = () => { num.value = rng.value; setParam(sp.name, +rng.value, true); };
        num.oninput = () => { rng.value = num.value; setParam(sp.name, +num.value, true); };
        row.appendChild(rng);
      } else { num.oninput = () => setParam(sp.name, +num.value, true); }
    }
    box.appendChild(row);
  }
  S.params = next;
}
function setParam(name, value, debounce) {
  S.params[name] = value;
  clearTimeout(S.buildTimer);
  S.buildTimer = setTimeout(build, debounce ? 250 : 0);
}
$('btnReset').onclick = () => { renderParams(false); build(); };
$('btnRebuild').onclick = () => build();

// ---------------------------------------------------------------- build
async function build() {
  if (!S.part) return;
  if (S.building) { S.queued = true; return; }
  S.building = true; status('building…');
  try {
    const t0 = performance.now();
    const r = await api('/api/build', { name: S.part, params: S.params });
    S.violations = r.violations; S.size = Math.max(...r.report.size);
    setMesh(r.mesh, r.edges, 45);
    if (!S.hasFit) { fitView('iso'); S.hasFit = true; }
    setMarkers(r.violations);
    renderChecks(r.violations);
    $('report').textContent = r.summary.split('\nchecks:')[0];
    const sz = r.report.size.map((x) => x.toFixed(1)).join(' × ');
    $('hud').innerHTML = `<span class="pill">${sz} mm</span><span class="pill">${Math.round(r.report.volume).toLocaleString()} mm³${r.report.mass_g ? ` · ${r.report.mass_g.toFixed(1)} g` : ''}</span><span class="pill">${r.report.n_solids} body · ${r.report.n_faces} faces</span>`;
    status(`built in ${r.build_seconds.toFixed(2)}s (round trip ${((performance.now() - t0) / 1000).toFixed(2)}s) · ${r.param_hash}`);
    markError(null);
  } catch (e) { showError(e); }
  S.building = false;
  if (S.queued) { S.queued = false; build(); }
}

function renderChecks(vs) {
  const box = $('checks'); box.innerHTML = '';
  const ne = vs.filter((v) => v.severity === 'error').length, nw = vs.filter((v) => v.severity === 'warn').length;
  $('checkCount').innerHTML = ne ? `<span style="color:var(--err)">${ne} error</span> · ${nw} warn` : nw ? `<span style="color:var(--warn)">${nw} warn</span>` : `<span style="color:var(--ok)">clean</span>`;
  vs.forEach((v, i) => {
    const d = document.createElement('div'); d.className = `v ${v.severity}`;
    d.innerHTML = `<b>${v.rule}</b> ${esc(v.message)}${v.fix ? `<div class="fix">→ ${esc(v.fix)}</div>` : ''}`;
    d.onclick = () => highlight(i); box.appendChild(d);
  });
  if (!vs.length) box.innerHTML = '<div class="v info">No issues found.</div>';
}

// ---------------------------------------------------------------- projects
async function loadProjects() {
  const r = await api('/api/projects');
  const sel = $('projectSel'); sel.innerHTML = '';
  for (const p of r.projects) { const o = document.createElement('option'); o.value = p.name; o.textContent = `${p.name} (${p.parts})`; sel.appendChild(o); }
  if (!r.projects.length) { const o = document.createElement('option'); o.textContent = '(no projects — click +)'; sel.appendChild(o); }
  sel.value = r.active;
}
$('projectSel').onchange = async () => {
  if (S.dirty && !confirm('Discard unsaved code changes?')) return;
  try { await api('/api/projects/select', { name: $('projectSel').value }); S.part = null; await loadParts(); } catch (e) { alert(e.message); }
};
$('btnNewProject').onclick = () => { $('projName').value = ''; $('modalProject').classList.add('open'); $('projName').focus(); };
$('projCancel').onclick = () => $('modalProject').classList.remove('open');
$('projCreate').onclick = async () => {
  const name = $('projName').value.trim(); if (!name) return;
  try { const r = await api('/api/projects/new', { name, starter: 'blank', part: 'part1' }); $('modalProject').classList.remove('open'); S.part = null; await loadProjects(); await loadParts(r.part); } catch (e) { alert(e.message); }
};
$('projName').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('projCreate').click(); });

// ---------------------------------------------------------------- parts list
async function loadParts(select) {
  const r = await api('/api/parts');
  $('project').textContent = r.project;
  const box = $('parts'); box.innerHTML = '';
  for (const p of r.parts) {
    const a = document.createElement('a'); a.className = p.name === S.part ? 'active' : '';
    a.innerHTML = `${p.name}<small>${esc(p.doc || '')}</small>`; a.onclick = () => openPart(p.name); box.appendChild(a);
  }
  if (select) openPart(select); else if (!S.part && r.parts.length) openPart(r.parts[0].name);
}
async function openPart(name) {
  if (S.dirty && !confirm('Discard unsaved code changes?')) return;
  S.part = name; S.hasFit = false; S.dirty = false; measureGroup.clear();
  document.querySelectorAll('.parts a').forEach((a) => a.classList.toggle('active', a.textContent.startsWith(name)));
  try {
    const r = await api(`/api/part/${name}`);
    S.source = r.source; cm.setValue(r.source); S.schema = r.schema;
    renderParams(false);
    if (r.schema.error) { showError({ message: r.schema.error, detail: r.schema.detail, line: r.schema.line }); return; }
    await build();
  } catch (e) { showError(e); }
}
$('btnRefresh').onclick = () => loadParts();

// new part
$('btnNew').onclick = async () => {
  const st = await api('/api/starters'); const box = $('starters'); box.innerHTML = ''; S.starter = 'blank';
  for (const s of st) { const d = document.createElement('div'); d.className = 'starter' + (s.name === 'blank' ? ' sel' : ''); d.innerHTML = `<b>${s.name}</b><div style="color:var(--muted)">${esc(s.doc)}</div>`; d.onclick = () => { S.starter = s.name; box.querySelectorAll('.starter').forEach((x) => x.classList.remove('sel')); d.classList.add('sel'); }; box.appendChild(d); }
  $('modalNew').classList.add('open'); $('newName').focus();
};
$('newCancel').onclick = () => $('modalNew').classList.remove('open');
$('newCreate').onclick = async () => {
  const name = $('newName').value.trim().replace(/[^\w-]/g, '_'); if (!name) return;
  try { const r = await api('/api/new', { name, starter: S.starter }); $('modalNew').classList.remove('open'); await loadParts(r.name); } catch (e) { alert(e.message); }
};

// export
$('btnExport').onclick = () => { $('exportResult').innerHTML = ''; $('modalExport').classList.add('open'); };
$('exportClose').onclick = () => $('modalExport').classList.remove('open');
document.querySelectorAll('#modalExport [data-fmt]').forEach((b) => (b.onclick = async () => {
  b.disabled = true; try {
    const r = await api('/api/export', { name: S.part, params: S.params, formats: [b.dataset.fmt] });
    for (const [fmt, f] of Object.entries(r.files)) $('exportResult').innerHTML += `<div>✓ <a href="/out/${encodeURIComponent(f)}" style="color:var(--accent)">${f}</a></div>`;
  } catch (e) { $('exportResult').innerHTML += `<div class="err">${esc(e.message)}</div>`; }
  b.disabled = false;
}));

// orient + guide
$('btnOrient').onclick = async () => {
  status('ranking orientations…');
  try { const r = await api('/api/orient', { name: S.part, params: S.params }); $('modalTextBody').innerHTML = `<h3 style="margin-top:0">Print orientation</h3><pre>${esc(r.text)}</pre>`; $('modalText').classList.add('open'); status('ready'); } catch (e) { showError(e); }
};
$('btnGuide').onclick = async () => { const t = await (await fetch('/api/guide')).text(); $('modalTextBody').innerHTML = marked.parse(t); $('modalText').classList.add('open'); };
$('textClose').onclick = () => $('modalText').classList.remove('open');
document.querySelectorAll('.modal').forEach((m) => m.addEventListener('click', (e) => { if (e.target === m) m.classList.remove('open'); }));

// ---------------------------------------------------------------- settings
async function loadSettings() {
  const r = await api('/api/settings');
  $('aiModel').textContent = r.has_key ? r.model : 'no API key — ⚙';
  $('keyHint').textContent = r.has_key ? `(saved: ${r.key_hint})` : '(none saved)';
  const sel = $('modelSel'); sel.innerHTML = '';
  for (const m of r.models) { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); }
  sel.value = r.model;
  return r;
}
$('btnSettings').onclick = async () => { await loadSettings(); $('apiKey').value = ''; $('modalSettings').classList.add('open'); };
$('settingsCancel').onclick = () => $('modalSettings').classList.remove('open');
$('settingsSave').onclick = async () => { await api('/api/settings', { api_key: $('apiKey').value, model: $('modelSel').value }); $('modalSettings').classList.remove('open'); await loadSettings(); };
$('keyClear').onclick = async () => { await api('/api/settings', { clear_key: true }); await loadSettings(); $('apiKey').value = ''; };

// ---------------------------------------------------------------- AI
function aiMsg(text, cls = '') { const d = document.createElement('div'); d.className = 'msg ' + cls; d.textContent = text; $('aiLog').appendChild(d); $('aiLog').scrollTop = 1e9; return d; }
async function aiSend() {
  const prompt = $('aiPrompt').value.trim(); if (!prompt || !S.part) return;
  if (S.dirty) { if (!confirm('Save your code changes first?')) return; await saveAndBuild(); }
  const st = await loadSettings();
  if (!st.has_key) { $('btnSettings').click(); return; }
  $('aiSend').disabled = true; $('aiStatus').textContent = 'thinking…'; aiMsg('▶ ' + prompt, 'ok');
  $('aiPrompt').value = '';
  try {
    const { id } = await api('/api/ai', { name: S.part, prompt });
    let since = 0, builds = 0;
    while (true) {
      await new Promise((r) => setTimeout(r, 1200));
      const j = await api(`/api/ai/${id}?since=${since}`);
      since = j.next;
      for (const ev of j.events) {
        if (ev.kind === 'text') aiMsg(ev.text);
        else if (ev.kind === 'tool') aiMsg('⚙ ' + ev.summary, 'tool');
        else if (ev.kind === 'build') { builds++; aiMsg(`build ${builds}: ${ev.ok ? 'clean' : 'has errors'} — ${ev.summary.split('\n').find((l) => l.startsWith('checks:')) || ''}`, 'tool'); }
      }
      if (j.changed) { $('aiStatus').textContent = `working… (${builds} builds)`; }
      if (j.done) { if (j.error) aiMsg('✗ ' + j.error, 'bad'); break; }
    }
    // reload the part the AI edited
    const r = await api(`/api/part/${S.part}`); S.source = r.source; cm.setValue(r.source); S.dirty = false; S.schema = r.schema; renderParams(true); await build();
  } catch (e) { aiMsg('✗ ' + e.message, 'bad'); }
  $('aiSend').disabled = false; $('aiStatus').textContent = '';
}
$('aiSend').onclick = aiSend;
$('aiPrompt').addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') aiSend(); });

loadProjects().then(() => loadParts()); loadSettings();
