"""MCP server: lets an AI drive forge end to end.

Design rule: one call = one full iteration.  ``build`` returns the report,
the violations and a render in a single response, so the model never needs
three round-trips to learn whether a change worked.

Run:  forge mcp [project_dir]      (stdio transport)
"""
from __future__ import annotations

import base64
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Optional

try:                                   # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP, Image
except ImportError:                    # mcp 1.x
    from mcp.server.fastmcp import FastMCP, Image

from . import PartError, build_part, export as _export, library, load_part, orient as _orient
from .render import markers_from_violations, render as _render, section as _section

PROJECT = Path(".").resolve()
STARTERS = Path(__file__).resolve().parent.parent / "starters"
GUIDE = Path(__file__).resolve().parent.parent / "docs" / "WRITING_PARTS.md"

mcp = FastMCP("forge", instructions=(
    "Forge is a code-first parametric CAD tool for 3D-printed and machined parts. "
    "Parts are Python files using build123d plus forge helpers. Call `guide` once to learn "
    "the part-file contract and FDM design rules, then write/patch a part and call `build`; "
    "read the violations and the render, fix, repeat. Export when checks are clean."
))


def _resolve(name: str) -> Path:
    p = Path(name)
    if not p.suffix:
        p = p.with_suffix(".py")
    if not p.is_absolute():
        p = PROJECT / p
    return p


def _out() -> Path:
    o = PROJECT / "out"
    o.mkdir(exist_ok=True)
    return o


def _err(e: Exception) -> str:
    if isinstance(e, PartError):
        s = f"ERROR: {e}"
        if e.detail:
            s += "\n" + e.detail
        if e.line:
            s += f"\n(part file line {e.line})"
        return s
    return "ERROR: " + "".join(traceback.format_exception_only(type(e), e)).strip()


# --------------------------------------------------------------------------
@mcp.tool()
def guide(topic: str = "all") -> str:
    """How to write a forge part file, the FDM/CNC design rules, the helper
    features and the standard-parts library.  Call this first in a new session.
    topic: all | contract | fdm | features | library | selectors"""
    text = GUIDE.read_text() if GUIDE.exists() else "guide missing"
    if topic == "all":
        return text
    # crude section slicing by '## ' headings containing the topic word
    parts = text.split("\n## ")
    hits = [p for p in parts if topic.lower() in p.lower()[:80]]
    return ("\n## ".join([""] + hits)).strip() or text


@mcp.tool()
def list_parts() -> str:
    """List part files in the project with their one-line description."""
    rows = []
    for p in sorted(PROJECT.glob("*.py")):
        if p.name.startswith("_"):
            continue
        try:
            pm = load_part(p)
            rows.append(f"{p.name:<28s} {pm.process.describe():<36s} {pm.doc.splitlines()[0] if pm.doc else ''}")
        except PartError as e:
            rows.append(f"{p.name:<28s} (broken: {e})")
    return "\n".join(rows) or f"no part files in {PROJECT}"


@mcp.tool()
def read_part(name: str) -> str:
    """Return the full source of a part file."""
    p = _resolve(name)
    if not p.exists():
        return f"ERROR: {p} does not exist"
    return p.read_text()


@mcp.tool()
def write_part(name: str, source: str) -> str:
    """Create or overwrite a part file with the given Python source, then
    try to load it (syntax/import check).  Does not build."""
    p = _resolve(name)
    p.write_text(source)
    try:
        pm = load_part(p)
        return f"wrote {p.name} ({len(source)} chars); params: {[s['name'] for s in pm.params_cls.specs()]}; process: {pm.process.describe()}"
    except PartError as e:
        return f"wrote {p.name} but it does not load:\n{_err(e)}"


@mcp.tool()
def patch_part(name: str, find: str, replace: str) -> str:
    """Replace exactly one occurrence of `find` with `replace` in a part file.
    Fails if the text is missing or ambiguous, so nothing silently changes."""
    p = _resolve(name)
    src = p.read_text()
    n = src.count(find)
    if n == 0:
        return "ERROR: text not found; read_part and copy the exact text"
    if n > 1:
        return f"ERROR: text occurs {n} times; include more context"
    p.write_text(src.replace(find, replace, 1))
    try:
        load_part(p)
        return "patched; loads OK"
    except PartError as e:
        return "patched but it does not load:\n" + _err(e)


@mcp.tool()
def build(name: str, params: Optional[dict] = None, views: str = "iso,front,top,right",
          render_png: bool = True, highlight_overhangs: bool = True) -> list:
    """Build a part with optional parameter overrides.  Returns the measurement
    report, all DFM violations with suggested fixes, and (by default) a PNG with
    four views, red-tinted where overhangs exceed the limit and dots where
    violations are.  This is the main loop: build → read → fix → build."""
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params)
    except Exception as e:
        return [_err(e)]
    out = [built.summary()]
    if render_png:
        png = _out() / f"{pm.name}-{built.params.hash()}.png"
        _render(built.shape, png, views=[v.strip() for v in views.split(",")],
                markers=markers_from_violations(built.violations),
                highlight_overhangs=highlight_overhangs,
                overhang_limit=getattr(pm.process, "max_overhang", 45.0))
        out.append(Image(path=str(png)))
    return out


@mcp.tool()
def section(name: str, plane: str = "XZ", offset: float = 0.0, params: Optional[dict] = None) -> list:
    """Render a cross-section.  plane: XZ (cut at Y=offset), YZ (cut at X=offset), XY (cut at Z=offset)."""
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params, check=False)
        png = _out() / f"{pm.name}-{built.params.hash()}-sec{plane}{offset:g}.png"
        _section(built.shape, png, plane, offset)
        return [f"section {plane} at {offset}", Image(path=str(png))]
    except Exception as e:
        return [_err(e)]


@mcp.tool()
def view(name: str, views: str = "under,iso2", params: Optional[dict] = None) -> list:
    """Extra renders.  Views: iso, iso2, front, back, top, bottom, right, left, under (looks up at overhangs)."""
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params, check=False)
        png = _out() / f"{pm.name}-{built.params.hash()}-{views.replace(',', '_')}.png"
        _render(built.shape, png, views=[v.strip() for v in views.split(",")], highlight_overhangs=True)
        return [Image(path=str(png))]
    except Exception as e:
        return [_err(e)]


@mcp.tool()
def orient(name: str, params: Optional[dict] = None) -> str:
    """Rank the six axis orientations for printing (overhang area, bridges, footprint, height)."""
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params, check=False)
        return _orient.summary(_orient.rank(built.shape, getattr(pm.process, "max_overhang", 45.0),
                                            getattr(pm.process, "max_bridge", 10.0)))
    except Exception as e:
        return _err(e)


@mcp.tool()
def export(name: str, formats: str = "3mf,step", params: Optional[dict] = None) -> str:
    """Export the built part.  formats: comma list of stl, 3mf, step, glb, svg, json.
    File names include the parameter hash."""
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params)
        written = _export(built, [f.strip() for f in formats.split(",")], _out())
        lines = [f"{k}: {v}" for k, v in written.items()]
        if not built.ok:
            lines.append(f"NOTE: exported with {len(built.errors)} unresolved error(s)")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool()
def measure(name: str, code: str, params: Optional[dict] = None) -> str:
    """Run arbitrary Python against the built shape for ad-hoc measurement.
    In scope: `shape` (the solid), `report`, everything from build123d, and
    `math`.  Print or return what you want to know, e.g.
      "top = shape.faces().sort_by(Axis.Z)[-1]; print(top.area, top.center())"
      "print([round(e.length,2) for e in shape.edges().filter_by(GeomType.CIRCLE)])"
    """
    try:
        pm = load_part(_resolve(name))
        built = build_part(pm, params, check=False)
    except Exception as e:
        return _err(e)
    import math
    import build123d as b3d
    ns = {"shape": built.shape, "report": built.report, "math": math, "params": built.params, **vars(b3d)}
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        try:
            result = eval(code, ns)  # expression?
            if result is not None:
                print(repr(result))
        except SyntaxError:
            exec(code, ns)
    except Exception as e:
        return buf.getvalue() + "ERROR: " + "".join(traceback.format_exception_only(type(e), e))
    finally:
        sys.stdout = old
    return buf.getvalue() or "(no output)"


@mcp.tool()
def starters() -> str:
    """List starter templates (copy one with `new_part`)."""
    rows = []
    for p in sorted(STARTERS.glob("*.py")):
        try:
            d = load_part(p).doc.splitlines()[0]
        except Exception as e:
            d = f"(broken: {e})"
        rows.append(f"{p.stem:<22s} {d}")
    return "\n".join(rows)


@mcp.tool()
def new_part(name: str, starter: str = "blank") -> str:
    """Create a new part file in the project from a starter template."""
    src = STARTERS / f"{starter}.py"
    if not src.exists():
        return f"ERROR: no starter {starter!r}"
    dst = _resolve(name)
    if dst.exists():
        return f"ERROR: {dst.name} already exists"
    dst.write_text(src.read_text())
    return f"created {dst.name} from {starter}\n\n{dst.read_text()}"


@mcp.tool()
def lookup(kind: str, key: str = "") -> str:
    """Standard dimensions.  kind: screw | heatset | bearing | magnet | fits | fdm.
    key: e.g. M3, 608, 6x3.  Empty key lists what's available."""
    tables = {"screw": library.METRIC_SCREWS, "heatset": library.HEATSET_INSERTS,
              "bearing": library.BEARINGS, "magnet": library.MAGNETS, "fits": library.FDM_FITS}
    if kind == "fdm":
        return json.dumps(library.fdm_guidance(), indent=1)
    t = tables.get(kind)
    if t is None:
        return f"ERROR: kind must be one of {list(tables) + ['fdm']}"
    if not key:
        return ", ".join(t.keys())
    k = key.upper() if kind in ("screw", "heatset", "bearing") else key.lower()
    return json.dumps(t.get(k, f"unknown {key!r}"), default=str)


def main(project: Path = Path(".")):
    global PROJECT
    PROJECT = Path(project).resolve()
    mcp.run()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))
