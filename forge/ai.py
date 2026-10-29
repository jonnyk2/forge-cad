"""In-app AI: a small agent loop over the Claude API.

The model gets the part-writing guide as its system prompt, sees the current
part (source + last build report), and has four tools: read_part, write_part,
patch_part, build.  `build` returns the measurement report, the violations and
a rendered PNG, so each turn is a full design iteration.

Jobs run in a background thread; the web UI polls `Job.events`.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import traceback
import uuid
from pathlib import Path
from typing import Optional

from . import PartError, build_part, load_part
from .render import markers_from_violations, render

CONFIG_PATH = Path.home() / ".forge" / "config.json"
DEFAULT_MODEL = "claude-sonnet-5-5"
MODELS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5"]
GUIDE = Path(__file__).resolve().parent.parent / "docs" / "WRITING_PARTS.md"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def api_key() -> Optional[str]:
    return os.environ.get("ANTHROPIC_API_KEY") or load_config().get("api_key")


SYSTEM = """You are the design engine inside Forge, a code-first parametric CAD tool for 3D-printed and machined parts.
You turn the user's request into a working part file, then iterate until the manufacturability checks are clean.

Workflow, every time:
1. If a part is open, read it (read_part) before changing it. Keep the user's parameters and style; extend, don't rewrite, unless asked.
2. Write or patch the part file. Keep Params meaningful with min/max/step/doc so the sliders are useful.
3. Call build. Read the report, the violations and the render carefully. Fix real problems (errors always; warnings when they matter for this part). Re-build.
4. Stop when the build is clean or the remaining warnings are acceptable, and tell the user in 2-4 sentences what you made, the key dimensions, and anything they should know before printing.

Rules: millimetres; +Z is up and Z=0 is the print bed; the part must rest flat; use forge helpers for holes (screw_hole, pin_hole, heatset_boss ...); never leave tiny slivers (< 0.8 mm) between features; prefer chamfers under overhangs. Do at most 6 builds per request.

The complete part-file contract and design rules follow.

""" + (GUIDE.read_text() if GUIDE.exists() else "")

TOOLS = [
    {"name": "read_part", "description": "Return the full source of the current part file.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "write_part", "description": "Replace the whole part file with new Python source (use for new parts or big changes).",
     "input_schema": {"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]}},
    {"name": "patch_part", "description": "Replace exactly one occurrence of `find` with `replace` in the part file. Fails if missing or ambiguous.",
     "input_schema": {"type": "object", "properties": {"find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["find", "replace"]}},
    {"name": "build", "description": "Build the part with its default parameters (or overrides). Returns the measurement report, DFM violations with fixes, and a 4-view render (overhangs tinted red, violation dots).",
     "input_schema": {"type": "object", "properties": {"params": {"type": "object", "description": "optional parameter overrides"}}}},
]


class Job:
    def __init__(self, part_path: Path, prompt: str, model: str, out_dir: Path):
        self.id = uuid.uuid4().hex[:8]
        self.part_path = part_path
        self.prompt = prompt
        self.model = model
        self.out_dir = out_dir
        self.events: list[dict] = []
        self.done = False
        self.error: Optional[str] = None
        self.final: str = ""
        self.changed = False
        self._lock = threading.Lock()

    def emit(self, kind: str, **data):
        with self._lock:
            self.events.append({"kind": kind, **data})
        self._persist()

    def _persist(self):
        """Keep the job log on disk so a server restart (UPDATE.bat, auto-reload)
        doesn't turn into a blank 'no such job'."""
        try:
            (self.out_dir / f"ai-{self.id}.json").write_text(json.dumps(self.snapshot(), default=str))
        except Exception:
            pass

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            return {"id": self.id, "events": self.events[since:], "next": len(self.events),
                    "done": self.done, "error": self.error, "final": self.final, "changed": self.changed}

    # ---- tools ---------------------------------------------------------
    def _tool(self, name: str, inp: dict):
        p = self.part_path
        if name == "read_part":
            return [{"type": "text", "text": p.read_text() if p.exists() else "(file does not exist yet)"}]
        if name == "write_part":
            p.write_text(inp["source"])
            self.changed = True
            try:
                pm = load_part(p)
                return [{"type": "text", "text": f"wrote {p.name}; loads OK; params: {[s['name'] for s in pm.params_cls.specs()]}"}]
            except PartError as e:
                return [{"type": "text", "text": f"wrote {p.name} but it does not load:\n{e}\n{e.detail}"}]
        if name == "patch_part":
            src = p.read_text()
            n = src.count(inp["find"])
            if n != 1:
                return [{"type": "text", "text": f"ERROR: `find` text occurs {n} times; read_part and copy exact text with more context"}]
            p.write_text(src.replace(inp["find"], inp["replace"], 1))
            self.changed = True
            try:
                load_part(p)
                return [{"type": "text", "text": "patched; loads OK"}]
            except PartError as e:
                return [{"type": "text", "text": f"patched but it does not load:\n{e}\n{e.detail}"}]
        if name == "build":
            try:
                pm = load_part(p)
                built = build_part(pm, inp.get("params") or None)
            except PartError as e:
                return [{"type": "text", "text": f"BUILD FAILED: {e}\n{e.detail}"}]
            except Exception as e:
                return [{"type": "text", "text": f"BUILD FAILED: {type(e).__name__}: {e}"}]
            png = self.out_dir / f"{pm.name}-{built.params.hash()}-ai.png"
            content = [{"type": "text", "text": built.summary()}]
            try:
                render(built.shape, png, markers=markers_from_violations(built.violations), highlight_overhangs=True,
                       overhang_limit=getattr(pm.process, "max_overhang", 45.0), size=700)
                data = base64.b64encode(png.read_bytes()).decode()
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
                self.emit("render", path=png.name)
            except Exception as e:
                content.append({"type": "text", "text": f"(render failed: {e})"})
            self.emit("build", ok=built.ok, summary=built.summary())
            return content
        return [{"type": "text", "text": f"unknown tool {name}"}]

    # ---- loop ----------------------------------------------------------
    def run(self):
        try:
            import anthropic
        except ImportError:
            self.error = "the `anthropic` package is not installed: run INSTALL_AND_TEST.bat again (or pip install anthropic)"
            self.done = True
            return
        key = api_key()
        if not key:
            self.error = "no API key: open Settings (gear icon) and paste an Anthropic API key"
            self.done = True
            return
        client = anthropic.Anthropic(api_key=key)
        exists = self.part_path.exists()
        ctx = f"Current part file: {self.part_path.name} ({'exists' if exists else 'does not exist yet - create it with write_part'})."
        messages = [{"role": "user", "content": f"{ctx}\n\nRequest: {self.prompt}"}]
        try:
            for turn in range(14):
                resp = client.messages.create(model=self.model, max_tokens=8000, system=SYSTEM, tools=TOOLS, messages=messages)
                messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
                tool_uses = [b for b in resp.content if b.type == "tool_use"]
                for b in resp.content:
                    if b.type == "text" and b.text.strip():
                        self.emit("text", text=b.text)
                        self.final = b.text
                if not tool_uses or resp.stop_reason == "end_turn":
                    break
                results = []
                for tu in tool_uses:
                    self.emit("tool", name=tu.name, summary=_tool_summary(tu.name, tu.input))
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": self._tool(tu.name, tu.input)})
                messages.append({"role": "user", "content": results})
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.emit("text", text=traceback.format_exc()[-800:])
        self.done = True
        self._persist()


def _tool_summary(name, inp) -> str:
    if name == "write_part":
        return f"write_part ({len(inp.get('source', ''))} chars)"
    if name == "patch_part":
        return f"patch_part: {inp.get('find', '')[:60]!r} → {inp.get('replace', '')[:60]!r}"
    if name == "build":
        return "build" + (f" {inp['params']}" if inp.get("params") else "")
    return name


JOBS: dict[str, Job] = {}


def snapshot_or_file(job_id: str, out_dir: Path, since: int = 0) -> Optional[dict]:
    job = JOBS.get(job_id)
    if job:
        return job.snapshot(since)
    f = out_dir / f"ai-{job_id}.json"
    if not f.exists():
        return None
    snap = json.loads(f.read_text())
    if not snap.get("done"):
        snap["done"] = True
        snap["error"] = "the server restarted while this request was running (an update?) — please send it again"
    snap["events"] = snap["events"][since:]
    return snap


def start(part_path: Path, prompt: str, model: str, out_dir: Path) -> Job:
    job = Job(part_path, prompt, model or load_config().get("model") or DEFAULT_MODEL, out_dir)
    JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return job
