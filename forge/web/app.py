"""Local web app for operating forge without the AI.

    forge serve [project_dir]  →  http://localhost:8765

Everything the UI does goes through the same Python API the MCP server uses.
"""
from __future__ import annotations

import json
import shutil
import threading
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .. import PartError, build_part, export as _export, library, load_part, orient as _orient
from .. import ai, commands as C, topology as T
from ..export import edges_json, mesh_json
from ..render import section as _section

HERE = Path(__file__).resolve().parent
STARTERS = HERE.parent.parent / "starters"
DOCS = HERE.parent.parent / "docs"

app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")
ROOT = Path(".").resolve()       # folder that holds projects (each project = a subfolder)


def _is_project(d: Path) -> bool:
    return d.is_dir() and not d.name.startswith((".", "_")) and d.name != "out" and any(d.glob("*.py"))


def _projects() -> list[Path]:
    subs = [d for d in sorted(ROOT.iterdir()) if _is_project(d)] if ROOT.is_dir() else []
    return subs


def _ensure_root():
    """If the served folder has no projects yet, seed an `examples` project from the starters."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if not _projects() and not any(ROOT.glob("*.py")):
        ex = ROOT / "examples"
        ex.mkdir(exist_ok=True)
        for f in STARTERS.glob("*.py"):
            shutil.copy(f, ex / f.name)


def _project() -> Path:
    """The project this request is about: ?project= / body.project, else the first one."""
    name = request.args.get("project") or ((request.get_json(silent=True) or {}).get("project") if request.is_json else None)
    if name:
        if ".." in name or "/" in name or "\\" in name:
            raise ValueError("bad project name")
        d = ROOT / name
        if _is_project(d):
            return d
        raise ValueError(f"no project {name!r}")
    projs = _projects()
    return projs[0] if projs else ROOT


def _resolve(name: str) -> Path:
    p = Path(name)
    if not p.suffix:
        p = p.with_suffix(".py")
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("part names are relative to the project")
    return _project() / p


def _out() -> Path:
    o = _project() / "out"
    o.mkdir(exist_ok=True)
    return o


def _error(e: Exception, status=400):
    body = {"error": str(e)}
    if isinstance(e, PartError):
        body["detail"] = e.detail
        body["line"] = e.line
    else:
        body["detail"] = traceback.format_exc()
    return jsonify(body), status


@app.get("/")
def index():
    from .. import __version__
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/app.js", f"/static/app.js?v={__version__}")
    return Response(html, mimetype="text/html")


@app.after_request
def _no_cache(resp):
    # the app is local and changes often: never let the browser serve a stale script
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/parts")
def api_parts():
    rows = []
    proj = _project()
    for p in sorted(proj.glob("*.py")):
        if p.name.startswith("_"):
            continue
        row = {"name": p.stem, "file": p.name}
        try:
            pm = load_part(p)
            row.update(doc=pm.doc.splitlines()[0] if pm.doc else "", process=pm.process.describe(), ok=True)
        except Exception as e:
            row.update(doc=f"broken: {e}", ok=False)
        rows.append(row)
    return jsonify({"project": str(proj), "parts": rows})


@app.get("/api/part/<name>")
def api_part(name):
    try:
        path = _resolve(name)
        src = path.read_text()
        try:
            pm = load_part(path)
            schema = pm.schema()
        except PartError as e:
            schema = {"name": name, "params": [], "error": str(e), "detail": e.detail, "line": e.line}
        return jsonify({"source": src, "schema": schema})
    except Exception as e:
        return _error(e)


@app.post("/api/part/<name>/source")
def api_save(name):
    try:
        path = _resolve(name)
        src = request.json["source"]
        _push_history(path)
        path.write_text(src)
        pm = load_part(path)
        return jsonify({"ok": True, "schema": pm.schema()})
    except Exception as e:
        return _error(e)


@app.post("/api/build")
def api_build():
    data = request.json or {}
    try:
        pm = load_part(_resolve(data["name"]))
        built = build_part(pm, data.get("params") or None, inspect_samples=int(data.get("samples", 3)))
        res = built.to_dict()
        res["summary"] = built.summary()
        res["topo"] = T.viewer_payload(built.shape, tolerance=float(data.get("tolerance", 0.05)))
        return jsonify(res)
    except Exception as e:
        return _error(e)


@app.post("/api/export")
def api_export():
    data = request.json or {}
    try:
        pm = load_part(_resolve(data["name"]))
        built = build_part(pm, data.get("params") or None)
        written = _export(built, data.get("formats", ["3mf"]), _out())
        return jsonify({"files": {k: Path(v).name for k, v in written.items()}})
    except Exception as e:
        return _error(e)


@app.get("/out/<path:fname>")
def api_out(fname):
    return send_from_directory(str(_out()), fname, as_attachment=True)


@app.post("/api/orient")
def api_orient():
    data = request.json or {}
    try:
        pm = load_part(_resolve(data["name"]))
        built = build_part(pm, data.get("params") or None, check=False)
        ranked = _orient.rank(built.shape, getattr(pm.process, "max_overhang", 45.0), getattr(pm.process, "max_bridge", 10.0))
        return jsonify({"ranked": [o.to_dict() for o in ranked], "text": _orient.summary(ranked)})
    except Exception as e:
        return _error(e)


@app.get("/api/starters")
def api_starters():
    rows = []
    for p in sorted(STARTERS.glob("*.py")):
        try:
            d = load_part(p).doc.splitlines()[0]
        except Exception as e:
            d = f"broken: {e}"
        rows.append({"name": p.stem, "doc": d})
    return jsonify(rows)


@app.post("/api/new")
def api_new():
    data = request.json or {}
    try:
        src = STARTERS / f"{data.get('starter', 'blank')}.py"
        dst = _resolve(data["name"])
        if dst.exists():
            raise ValueError(f"{dst.name} already exists")
        dst.write_text(src.read_text())
        return jsonify({"ok": True, "name": dst.stem})
    except Exception as e:
        return _error(e)


@app.get("/api/library")
def api_library():
    return jsonify({"screws": library.METRIC_SCREWS, "heatset": library.HEATSET_INSERTS,
                    "bearings": library.BEARINGS, "magnets": library.MAGNETS,
                    "fits": library.FDM_FITS, "fdm": library.fdm_guidance()})


@app.get("/api/guide")
def api_guide():
    g = DOCS / "WRITING_PARTS.md"
    return Response(g.read_text() if g.exists() else "", mimetype="text/markdown")


@app.get("/api/projects")
def api_projects():
    projs = _projects()
    return jsonify({"root": str(ROOT), "active": projs[0].name if projs else "",
                    "projects": [{"name": d.name, "parts": len(list(d.glob("*.py")))} for d in projs]})


@app.post("/api/projects/select")
def api_project_select():
    name = (request.json or {}).get("name", "")
    if not name or ".." in name or not _is_project(ROOT / name):
        return jsonify({"error": f"no project {name!r}"}), 400
    return jsonify({"ok": True, "active": name})


@app.post("/api/projects/new")
def api_project_new():
    data = request.json or {}
    name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in data.get("name", "")).strip().replace(" ", "_")
    if not name:
        return jsonify({"error": "project needs a name"}), 400
    d = ROOT / name
    if d.exists():
        return jsonify({"error": f"{name} already exists"}), 400
    d.mkdir(parents=True)
    starter = data.get("starter") or "blank"
    src = STARTERS / f"{starter}.py"
    first = d / f"{data.get('part') or starter}.py"
    first.write_text(src.read_text())
    return jsonify({"ok": True, "active": name, "part": first.stem})


@app.get("/api/settings")
def api_settings_get():
    cfg = ai.load_config()
    key = ai.api_key() or ""
    return jsonify({"has_key": bool(key), "key_hint": (key[:7] + "…" + key[-4:]) if len(key) > 12 else "",
                    "model": cfg.get("model", ai.DEFAULT_MODEL), "models": ai.MODELS})


@app.post("/api/settings")
def api_settings_set():
    data = request.json or {}
    cfg = ai.load_config()
    if data.get("api_key"):
        cfg["api_key"] = data["api_key"].strip()
    if data.get("clear_key"):
        cfg.pop("api_key", None)
    if data.get("model"):
        cfg["model"] = data["model"]
    ai.save_config(cfg)
    return api_settings_get()


@app.post("/api/ai")
def api_ai_start():
    data = request.json or {}
    try:
        path = _resolve(data["name"])
        job = ai.start(path, data["prompt"], data.get("model"), _out())
        return jsonify({"id": job.id})
    except Exception as e:
        return _error(e)


@app.get("/api/ai/<job_id>")
def api_ai_poll(job_id):
    snap = ai.snapshot_or_file(job_id, _out(), int(request.args.get("since", 0)))
    if snap is None:
        return jsonify({"error": "no such job"}), 404
    return jsonify(snap)


# ---- model-level undo/redo (per part file) ---------------------------------
_HISTORY: dict[str, list[str]] = {}
_REDO: dict[str, list[str]] = {}


def _push_history(path: Path):
    if path.exists():
        _HISTORY.setdefault(str(path), []).append(path.read_text())
        _HISTORY[str(path)] = _HISTORY[str(path)][-50:]
        _REDO.pop(str(path), None)


@app.post("/api/undo")
def api_undo():
    try:
        path = _resolve((request.json or {})["name"])
        stack = _HISTORY.get(str(path)) or []
        if not stack:
            return jsonify({"error": "nothing to undo"}), 400
        _REDO.setdefault(str(path), []).append(path.read_text())
        path.write_text(stack.pop())
        return jsonify({"ok": True, "remaining": len(stack)})
    except Exception as e:
        return _error(e)


@app.post("/api/redo")
def api_redo():
    try:
        path = _resolve((request.json or {})["name"])
        stack = _REDO.get(str(path)) or []
        if not stack:
            return jsonify({"error": "nothing to redo"}), 400
        _HISTORY.setdefault(str(path), []).append(path.read_text())
        path.write_text(stack.pop())
        return jsonify({"ok": True})
    except Exception as e:
        return _error(e)


# ---- selection → selector, measure --------------------------------------
@app.post("/api/selector")
def api_selector():
    """{name, params, kind: faces|edges, index} → {expr, stable}"""
    data = request.json or {}
    try:
        pm = load_part(_resolve(data["name"]))
        built = build_part(pm, data.get("params") or None, check=False)
        var = C.find_build_site(pm.path.read_text()).var or "part"
        return jsonify(T.resolve_selector(built.shape, data["kind"], int(data["index"]), var))
    except Exception as e:
        return _error(e)


@app.post("/api/measure")
def api_measure():
    """{name, params, items: [{kind, index}, ...]} → measurements of one or two items."""
    data = request.json or {}
    try:
        pm = load_part(_resolve(data["name"]))
        built = build_part(pm, data.get("params") or None, check=False)
        shape = built.shape
        faces, edges = list(shape.faces()), list(shape.edges())
        objs = []
        for it in data.get("items", [])[:2]:
            objs.append(faces[int(it["index"])] if it["kind"] == "faces" else edges[int(it["index"])])
        out = {}
        if len(objs) == 1:
            o = objs[0]
            out["info"] = T.face_info(o, 0) if o in faces else T.edge_info(o, 0)
        elif len(objs) == 2:
            a, b = objs
            out["distance"] = round(float(a.distance_to(b)), 3)
            ca, cb = a.center(), b.center()
            out["center_delta"] = [round(cb.X - ca.X, 3), round(cb.Y - ca.Y, 3), round(cb.Z - ca.Z, 3)]
            out["center_distance"] = round((cb - ca).length, 3)
            try:
                from ..inspect import face_angle
                if a in faces and b in faces:
                    out["angle"] = round(face_angle(a, b), 2)
            except Exception:
                pass
        return jsonify(out)
    except Exception as e:
        return _error(e)


# ---- commands that write code -------------------------------------------
@app.get("/api/commands")
def api_commands():
    return jsonify(C.catalog())


@app.post("/api/command/preview")
def api_command_preview():
    """{name, params, cmd, values} → build a temp copy with the generated code; returns code + topo + violations."""
    data = request.json or {}
    try:
        path = _resolve(data["name"])
        src = path.read_text()
        code = C.generate(data["cmd"], data.get("values") or {}, src)
        new_src, a, b = C.insert_into_build(src, code)
        tmp = path.with_name(f"_preview_{path.stem}.py")
        tmp.write_text(new_src)
        try:
            pm = load_part(tmp)
            built = build_part(pm, data.get("params") or None)
            res = {"code": code, "lines": [a, b], "ok": True, "summary": built.summary(),
                   "violations": [v.to_dict() for v in built.violations], "report": built.report.to_dict(),
                   "topo": T.viewer_payload(built.shape)}
        except Exception as e:
            res = {"code": code, "lines": [a, b], "ok": False, "error": str(e), "detail": getattr(e, "detail", "")}
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
        return jsonify(res)
    except Exception as e:
        return _error(e)


@app.post("/api/command/apply")
def api_command_apply():
    data = request.json or {}
    try:
        path = _resolve(data["name"])
        src = path.read_text()
        code = data.get("code") or C.generate(data["cmd"], data.get("values") or {}, src)
        new_src, a, b = C.insert_into_build(src, code)
        _push_history(path)
        path.write_text(new_src)
        pm = load_part(path)
        return jsonify({"ok": True, "lines": [a, b], "source": new_src, "schema": pm.schema()})
    except Exception as e:
        return _error(e)


def serve(project: Path = Path("."), port: int = 8765, open_browser: bool = True):
    global ROOT
    ROOT = Path(project).resolve()
    _ensure_root()
    url = f"http://127.0.0.1:{port}"
    print(f"forge: serving {ROOT} at {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    # no auto-reloader: it restarts the server whenever a .py file it noticed changes,
    # which includes part files being edited, and that kills in-flight AI jobs.
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)
