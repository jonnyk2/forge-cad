"""UI commands that write code.

Every Fusion-style command (Extrude, Hole, Fillet…) is a *spec* the web UI can
render as a dialog, plus a generator that turns the dialog's values and the
current selection into build123d lines.  `insert_into_build` puts those lines
at the end of the `with BuildPart() as <var>:` block of `build()` (or before
the `return` if there is no builder block), so the part file stays the single
source of truth.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------
# locating where to insert
# --------------------------------------------------------------------------

@dataclass
class BuildSite:
    var: str                 # name of the BuildPart builder (e.g. "part"), or "" if none
    insert_line: int         # 1-based line *before which* to insert
    indent: str              # indentation for inserted lines
    has_builder: bool


def find_build_site(source: str) -> BuildSite:
    tree = ast.parse(source)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build"), None)
    if fn is None:
        raise ValueError("part file has no build() function")
    lines = source.splitlines()
    # outermost `with BuildPart() as X:` directly in build()
    for node in fn.body:
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "BuildPart" and item.optional_vars is not None:
                    var = item.optional_vars.id
                    last = node.body[-1]
                    end = getattr(last, "end_lineno", last.lineno)
                    first = node.body[0]
                    indent = re.match(r"\s*", lines[first.lineno - 1]).group(0)
                    return BuildSite(var, end + 1, indent, True)
    # no builder block: insert before the final return
    ret = next((n for n in reversed(fn.body) if isinstance(n, ast.Return)), None)
    first = fn.body[0]
    indent = re.match(r"\s*", lines[first.lineno - 1]).group(0)
    line = ret.lineno if ret else (getattr(fn, "end_lineno", fn.lineno) + 1)
    return BuildSite("", line, indent, False)


def insert_into_build(source: str, code: str) -> tuple[str, int, int]:
    """Insert `code` (unindented lines) into build().  Returns (new_source, first_line, last_line)."""
    site = find_build_site(source)
    lines = source.splitlines()
    new = [site.indent + l if l.strip() else "" for l in code.rstrip("\n").splitlines()]
    at = site.insert_line - 1
    out = lines[:at] + new + lines[at:]
    return "\n".join(out) + ("\n" if source.endswith("\n") else ""), at + 1, at + len(new)


# --------------------------------------------------------------------------
# command specs
# --------------------------------------------------------------------------

@dataclass
class Field:
    name: str
    label: str
    kind: str = "number"         # number | choice | bool | text | selection
    default: Any = None
    choices: Optional[list[str]] = None
    unit: str = "mm"
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    select: str = ""             # for kind=selection: faces | edges | bodies | any
    multi: bool = False
    doc: str = ""

    def to_dict(self):
        d = self.__dict__.copy()
        return d


@dataclass
class Command:
    id: str
    label: str
    group: str                   # Create | Modify | Construct | Inspect | Pattern
    key: str = ""                # keyboard shortcut
    fields: list[Field] = field(default_factory=list)
    needs: str = ""              # selection the command wants when invoked: faces | edges | ""
    doc: str = ""
    gen: Callable[[dict, "BuildSite"], str] = None

    def to_dict(self):
        return {"id": self.id, "label": self.label, "group": self.group, "key": self.key, "needs": self.needs,
                "doc": self.doc, "fields": [f.to_dict() for f in self.fields]}


COMMANDS: dict[str, Command] = {}


def _cmd(**kw):
    def deco(fn):
        c = Command(gen=fn, **kw)
        COMMANDS[c.id] = c
        return fn
    return deco


def _n(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _mode(op: str) -> str:
    return {"join": "", "cut": ", mode=Mode.SUBTRACT", "intersect": ", mode=Mode.INTERSECT", "new": ", mode=Mode.ADD"}.get(op, "")


def _sel(v: dict, name: str) -> list[str]:
    """Selected selector expressions for a selection field (list of strings)."""
    s = v.get(name) or []
    if isinstance(s, str):
        s = [s]
    return [x for x in s if x]


def _plane_from_face(face_expr: str) -> str:
    return f"Plane({face_expr})"


OPS = ["join", "cut", "intersect", "new"]
SHAPES = ["Rectangle", "Circle", "RectangleRounded", "RegularPolygon", "Ellipse", "SlotCenterToCenter"]


def _shape_code(v: dict) -> str:
    sh = v.get("shape", "Rectangle")
    a, b = _n(v.get("size_a", 20)), _n(v.get("size_b", 10))
    r = _n(v.get("radius", 2))
    return {
        "Rectangle": f"Rectangle({a:g}, {b:g})",
        "RectangleRounded": f"RectangleRounded({a:g}, {b:g}, {min(r, min(a, b) / 2 - 0.01):g})",
        "Circle": f"Circle({a / 2:g})",
        "RegularPolygon": f"RegularPolygon({a / 2:g}, {int(_n(v.get('sides', 6), 6))})",
        "Ellipse": f"Ellipse({a / 2:g}, {b / 2:g})",
        "SlotCenterToCenter": f"SlotCenterToCenter({a:g}, {b:g})",
    }[sh]


# ---- Create ---------------------------------------------------------------

@_cmd(id="extrude", label="Extrude", group="Create", key="E", needs="faces",
      doc="Sketch a profile on the selected face (or a plane) and extrude it. Negative distance goes into the part; use Cut to remove material.",
      fields=[Field("on", "Sketch on", "selection", select="faces", doc="a planar face, or leave empty for the XY plane"),
              Field("shape", "Profile", "choice", "Rectangle", SHAPES),
              Field("size_a", "Size A (X / Ø / length)", default=20, min=0.1, step=0.5),
              Field("size_b", "Size B (Y / width)", default=10, min=0.1, step=0.5),
              Field("radius", "Corner radius", default=2, min=0, step=0.5),
              Field("sides", "Sides (polygon)", default=6, min=3, max=24, step=1, unit=""),
              Field("offset_x", "Offset X", default=0, step=0.5), Field("offset_y", "Offset Y", default=0, step=0.5),
              Field("distance", "Distance", default=10, step=0.5),
              Field("taper", "Taper angle", default=0, unit="deg", step=1),
              Field("both", "Symmetric (both sides)", "bool", False),
              Field("op", "Operation", "choice", "join", OPS)])
def _g_extrude(v, site):
    on = _sel(v, "on")
    plane = _plane_from_face(on[0]) if on else "Plane.XY"
    ox, oy = _n(v.get("offset_x")), _n(v.get("offset_y"))
    loc = f"    with Locations(({ox:g}, {oy:g})):\n    " if (ox or oy) else "    "
    d = _n(v.get("distance", 10))
    taper = _n(v.get("taper"))
    extra = (f", taper={taper:g}" if taper else "") + (", both=True" if v.get("both") else "") + _mode(v.get("op", "join"))
    return (f"with BuildSketch({plane}):\n{loc}{_shape_code(v)}\n"
            f"extrude(amount={d:g}{extra})")


@_cmd(id="revolve", label="Revolve", group="Create", needs="faces",
      doc="Sketch on a face/plane and revolve the profile about an axis.",
      fields=[Field("on", "Sketch on", "selection", select="faces"),
              Field("shape", "Profile", "choice", "Rectangle", SHAPES),
              Field("size_a", "Size A", default=10, step=0.5), Field("size_b", "Size B", default=5, step=0.5),
              Field("offset_x", "Offset X (from axis)", default=10, step=0.5), Field("offset_y", "Offset Y", default=0, step=0.5),
              Field("axis", "Axis", "choice", "Axis.Z", ["Axis.Z", "Axis.X", "Axis.Y"]),
              Field("angle", "Angle", default=360, unit="deg", min=1, max=360, step=5),
              Field("op", "Operation", "choice", "join", OPS)])
def _g_revolve(v, site):
    on = _sel(v, "on")
    plane = _plane_from_face(on[0]) if on else "Plane.XZ"
    ox, oy = _n(v.get("offset_x", 10)), _n(v.get("offset_y"))
    return (f"with BuildSketch({plane}):\n    with Locations(({ox:g}, {oy:g})):\n        {_shape_code(v)}\n"
            f"revolve(axis={v.get('axis', 'Axis.Z')}, revolution_arc={_n(v.get('angle', 360)):g}{_mode(v.get('op', 'join'))})")


@_cmd(id="hole", label="Hole", group="Create", key="H", needs="faces",
      doc="Drill a hole into the selected face, at its centre or at an offset. Screw sizes are compensated for the printer.",
      fields=[Field("on", "Face", "selection", select="faces"),
              Field("kind", "Type", "choice", "screw clearance", ["screw clearance", "screw tap", "heat-set insert", "counterbore", "countersink", "plain diameter"]),
              Field("screw", "Screw", "choice", "M3", ["M2", "M2.5", "M3", "M4", "M5", "M6", "M8"]),
              Field("diameter", "Diameter (plain)", default=5, min=0.5, step=0.1),
              Field("depth", "Depth (0 = through)", default=0, min=0, step=0.5),
              Field("offset_x", "Offset X", default=0, step=0.5), Field("offset_y", "Offset Y", default=0, step=0.5),
              Field("pattern", "Pattern", "choice", "single", ["single", "grid 2x2", "grid 2x1", "grid 1x2", "circle"]),
              Field("spacing_x", "Spacing X / circle Ø", default=20, step=1), Field("spacing_y", "Spacing Y", default=15, step=1),
              Field("count", "Count (circle)", default=4, min=2, max=36, step=1, unit="")])
def _g_hole(v, site):
    on = _sel(v, "on")
    face = on[0] if on else f"{site.var or 'part'}.faces().sort_by(Axis.Z)[-1]"
    depth = _n(v.get("depth"))
    dep = f", depth={depth:g}" if depth > 0 else ""
    kind = v.get("kind", "screw clearance")
    screw = v.get("screw", "M3")
    if kind == "plain diameter":
        call = f"Hole(radius={_n(v.get('diameter', 5)) / 2:g}{dep})"
    elif kind == "screw clearance":
        call = f"screw_hole(\"{screw}\"{dep})"
    elif kind == "screw tap":
        call = f"screw_hole(\"{screw}\", kind=\"tap\"{dep or ', depth=8'})"
    elif kind == "heat-set insert":
        call = f"screw_hole(\"{screw}\", kind=\"heatset\")"
    elif kind == "counterbore":
        call = f"screw_hole(\"{screw}\", counterbore=True{dep})"
    else:
        call = f"screw_hole(\"{screw}\", countersink=True{dep})"
    ox, oy = _n(v.get("offset_x")), _n(v.get("offset_y"))
    pat = v.get("pattern", "single")
    sx, sy, n = _n(v.get("spacing_x", 20)), _n(v.get("spacing_y", 15)), int(_n(v.get("count", 4), 4))
    inner = {"single": None, "grid 2x2": f"GridLocations({sx:g}, {sy:g}, 2, 2)", "grid 2x1": f"GridLocations({sx:g}, 0, 2, 1)",
             "grid 1x2": f"GridLocations(0, {sy:g}, 1, 2)", "circle": f"PolarLocations({sx / 2:g}, {n})"}[pat]
    lines = [f"with Locations({face}):"]
    ind = "    "
    if ox or oy:
        lines.append(f"{ind}with Locations(({ox:g}, {oy:g})):")
        ind += "    "
    if inner:
        lines.append(f"{ind}with {inner}:")
        ind += "    "
    lines.append(f"{ind}{call}")
    return "\n".join(lines)


@_cmd(id="box", label="Box", group="Create",
      fields=[Field("x", "Length X", default=20, step=1), Field("y", "Width Y", default=20, step=1), Field("z", "Height Z", default=10, step=1),
              Field("px", "Position X", default=0, step=1), Field("py", "Position Y", default=0, step=1), Field("pz", "Position Z", default=0, step=1),
              Field("op", "Operation", "choice", "join", OPS)])
def _g_box(v, site):
    return (f"with Locations(({_n(v.get('px')):g}, {_n(v.get('py')):g}, {_n(v.get('pz')):g})):\n"
            f"    Box({_n(v.get('x', 20)):g}, {_n(v.get('y', 20)):g}, {_n(v.get('z', 10)):g}, align=(Align.CENTER, Align.CENTER, Align.MIN){_mode(v.get('op', 'join'))})")


@_cmd(id="cylinder", label="Cylinder", group="Create",
      fields=[Field("d", "Diameter", default=10, step=0.5), Field("h", "Height", default=10, step=0.5),
              Field("px", "Position X", default=0, step=1), Field("py", "Position Y", default=0, step=1), Field("pz", "Position Z", default=0, step=1),
              Field("axis", "Axis", "choice", "Z", ["Z", "X", "Y"]),
              Field("op", "Operation", "choice", "join", OPS)])
def _g_cyl(v, site):
    rot = {"Z": "", "X": ", rotation=(0, 90, 0)", "Y": ", rotation=(90, 0, 0)"}[v.get("axis", "Z")]
    return (f"with Locations(({_n(v.get('px')):g}, {_n(v.get('py')):g}, {_n(v.get('pz')):g})):\n"
            f"    Cylinder({_n(v.get('d', 10)) / 2:g}, {_n(v.get('h', 10)):g}, align=(Align.CENTER, Align.CENTER, Align.MIN){rot}{_mode(v.get('op', 'join'))})")


@_cmd(id="sphere", label="Sphere", group="Create",
      fields=[Field("d", "Diameter", default=10, step=0.5), Field("px", "Position X", default=0, step=1),
              Field("py", "Position Y", default=0, step=1), Field("pz", "Position Z", default=5, step=1),
              Field("op", "Operation", "choice", "join", OPS)])
def _g_sphere(v, site):
    return (f"with Locations(({_n(v.get('px')):g}, {_n(v.get('py')):g}, {_n(v.get('pz', 5)):g})):\n"
            f"    Sphere({_n(v.get('d', 10)) / 2:g}{_mode(v.get('op', 'join'))})")


@_cmd(id="text", label="Text (emboss/engrave)", group="Create", needs="faces",
      fields=[Field("on", "Face", "selection", select="faces"), Field("text", "Text", "text", "FORGE"),
              Field("size", "Font size", default=8, min=2, step=0.5), Field("depth", "Depth (+ emboss / − engrave)", default=-0.6, step=0.2),
              Field("offset_x", "Offset X", default=0, step=0.5), Field("offset_y", "Offset Y", default=0, step=0.5)])
def _g_text(v, site):
    on = _sel(v, "on")
    plane = _plane_from_face(on[0]) if on else "Plane.XY"
    d = _n(v.get("depth", -0.6))
    mode = ", mode=Mode.SUBTRACT" if d < 0 else ""
    txt = str(v.get("text", "FORGE")).replace('"', '\\"')
    return (f"with BuildSketch({plane}):\n    with Locations(({_n(v.get('offset_x')):g}, {_n(v.get('offset_y')):g})):\n"
            f"        Text(\"{txt}\", font_size={_n(v.get('size', 8)):g})\n"
            f"extrude(amount={abs(d):g}{mode})")


# ---- Modify ---------------------------------------------------------------

@_cmd(id="fillet", label="Fillet", group="Modify", key="F", needs="edges",
      doc="Round the selected edges. Tip: fillet vertical edges freely; chamfer bottom edges instead.",
      fields=[Field("edges", "Edges", "selection", select="edges", multi=True), Field("radius", "Radius", default=2, min=0.1, step=0.5)])
def _g_fillet(v, site):
    e = _sel(v, "edges")
    if not e:
        e = [f"{site.var or 'part'}.edges().filter_by(Axis.Z)"]
    target = e[0] if len(e) == 1 else "[" + ", ".join(e) + "]"
    return f"fillet({target}, radius={_n(v.get('radius', 2)):g})"


@_cmd(id="chamfer", label="Chamfer", group="Modify", needs="edges",
      fields=[Field("edges", "Edges", "selection", select="edges", multi=True), Field("length", "Length", default=1, min=0.1, step=0.2),
              Field("length2", "Second length (0 = equal)", default=0, min=0, step=0.2)])
def _g_chamfer(v, site):
    e = _sel(v, "edges")
    if not e:
        e = [f"{site.var or 'part'}.faces().sort_by(Axis.Z)[0].edges()"]
    l2 = _n(v.get("length2"))
    extra = f", length2={l2:g}" if l2 > 0 else ""
    target = e[0] if len(e) == 1 else "[" + ", ".join(e) + "]"
    return f"chamfer({target}, length={_n(v.get('length', 1)):g}{extra})"


@_cmd(id="shell", label="Shell", group="Modify", needs="faces",
      doc="Hollow the body, removing the selected faces (open sides).",
      fields=[Field("open", "Open faces", "selection", select="faces", multi=True), Field("thickness", "Wall thickness", default=1.6, min=0.4, step=0.4)])
def _g_shell(v, site):
    o = _sel(v, "open")
    opening = o[0] if len(o) == 1 else ("[" + ", ".join(o) + "]" if o else "None")
    return f"offset(amount=-{_n(v.get('thickness', 1.6)):g}, openings={opening})"


@_cmd(id="move", label="Move / Rotate body", group="Modify", key="M",
      fields=[Field("dx", "Move X", default=0, step=1), Field("dy", "Move Y", default=0, step=1), Field("dz", "Move Z", default=0, step=1),
              Field("rx", "Rotate about X", default=0, unit="deg", step=5), Field("ry", "Rotate about Y", default=0, unit="deg", step=5),
              Field("rz", "Rotate about Z", default=0, unit="deg", step=5)])
def _g_move(v, site):
    var = site.var or "part"
    dx, dy, dz = _n(v.get("dx")), _n(v.get("dy")), _n(v.get("dz"))
    rx, ry, rz = _n(v.get("rx")), _n(v.get("ry")), _n(v.get("rz"))
    expr = f"{var}.part"
    for ax, a in (("Axis.X", rx), ("Axis.Y", ry), ("Axis.Z", rz)):
        if a:
            expr += f".rotate({ax}, {a:g})"
    if dx or dy or dz:
        expr += f".moved(Location(({dx:g}, {dy:g}, {dz:g})))"
    if expr == f"{var}.part":
        return "pass  # move: nothing to do"
    return f"add({expr}, mode=Mode.REPLACE)"


@_cmd(id="scale", label="Scale", group="Modify",
      fields=[Field("factor", "Factor", default=1.1, min=0.01, step=0.05, unit="×")])
def _g_scale(v, site):
    return f"scale(by={_n(v.get('factor', 1.1)):g})"


@_cmd(id="mirror", label="Mirror", group="Pattern",
      fields=[Field("plane", "About plane", "choice", "Plane.YZ", ["Plane.YZ", "Plane.XZ", "Plane.XY"])])
def _g_mirror(v, site):
    return f"mirror(about={v.get('plane', 'Plane.YZ')})"


@_cmd(id="pattern_rect", label="Rectangular pattern (of a cylinder cut/boss)", group="Pattern",
      doc="Repeats a feature: a cylinder boss or hole on the selected face in a grid.",
      fields=[Field("on", "Face", "selection", select="faces"), Field("d", "Feature Ø", default=4, step=0.5),
              Field("h", "Height (+ boss / − cut)", default=-5, step=0.5),
              Field("sx", "Spacing X", default=15, step=1), Field("sy", "Spacing Y", default=15, step=1),
              Field("nx", "Count X", default=3, min=1, max=50, step=1, unit=""), Field("ny", "Count Y", default=2, min=1, max=50, step=1, unit="")])
def _g_prect(v, site):
    on = _sel(v, "on")
    face = on[0] if on else f"{site.var or 'part'}.faces().sort_by(Axis.Z)[-1]"
    h = _n(v.get("h", -5))
    body = (f"Hole(radius={_n(v.get('d', 4)) / 2:g}, depth={abs(h):g})" if h < 0
            else f"Cylinder({_n(v.get('d', 4)) / 2:g}, {h:g}, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    return (f"with Locations({face}):\n    with GridLocations({_n(v.get('sx', 15)):g}, {_n(v.get('sy', 15)):g}, "
            f"{int(_n(v.get('nx', 3), 3))}, {int(_n(v.get('ny', 2), 2))}):\n        {body}")


@_cmd(id="pattern_circ", label="Circular pattern (of a cylinder cut/boss)", group="Pattern",
      fields=[Field("on", "Face", "selection", select="faces"), Field("d", "Feature Ø", default=4, step=0.5),
              Field("h", "Height (+ boss / − cut)", default=-5, step=0.5),
              Field("circle_d", "Pattern circle Ø", default=30, step=1), Field("n", "Count", default=6, min=2, max=72, step=1, unit="")])
def _g_pcirc(v, site):
    on = _sel(v, "on")
    face = on[0] if on else f"{site.var or 'part'}.faces().sort_by(Axis.Z)[-1]"
    h = _n(v.get("h", -5))
    body = (f"Hole(radius={_n(v.get('d', 4)) / 2:g}, depth={abs(h):g})" if h < 0
            else f"Cylinder({_n(v.get('d', 4)) / 2:g}, {h:g}, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    return (f"with Locations({face}):\n    with PolarLocations({_n(v.get('circle_d', 30)) / 2:g}, {int(_n(v.get('n', 6), 6))}):\n        {body}")


@_cmd(id="split", label="Split body (keep one side)", group="Modify",
      fields=[Field("plane", "Plane", "choice", "Plane.XY", ["Plane.XY", "Plane.XZ", "Plane.YZ"]), Field("offset", "Offset", default=0, step=0.5),
              Field("keep", "Keep", "choice", "top", ["top", "bottom", "both"])])
def _g_split(v, site):
    keep = {"top": "Keep.TOP", "bottom": "Keep.BOTTOM", "both": "Keep.BOTH"}[v.get("keep", "top")]
    return f"split(bisect_by={v.get('plane', 'Plane.XY')}.offset({_n(v.get('offset')):g}), keep={keep})"


# ---- Construct ------------------------------------------------------------

@_cmd(id="plane_offset", label="Offset plane (as variable)", group="Construct",
      doc="Defines a named plane you can sketch on later: `plane_1 = Plane.XY.offset(10)`.",
      fields=[Field("name", "Name", "text", "plane_1"), Field("base", "Base", "choice", "Plane.XY", ["Plane.XY", "Plane.XZ", "Plane.YZ"]),
              Field("offset", "Offset", default=10, step=0.5)])
def _g_plane(v, site):
    name = re.sub(r"\W", "_", str(v.get("name", "plane_1"))) or "plane_1"
    return f"{name} = {v.get('base', 'Plane.XY')}.offset({_n(v.get('offset', 10)):g})"


@_cmd(id="plane_face", label="Plane on face (as variable)", group="Construct", needs="faces",
      fields=[Field("name", "Name", "text", "plane_1"), Field("on", "Face", "selection", select="faces"), Field("offset", "Offset along normal", default=0, step=0.5)])
def _g_plane_face(v, site):
    on = _sel(v, "on")
    name = re.sub(r"\W", "_", str(v.get("name", "plane_1"))) or "plane_1"
    face = on[0] if on else f"{site.var or 'part'}.faces().sort_by(Axis.Z)[-1]"
    off = _n(v.get("offset"))
    return f"{name} = Plane({face})" + (f".offset({off:g})" if off else "")


# --------------------------------------------------------------------------

def generate(cmd_id: str, values: dict, source: str) -> str:
    cmd = COMMANDS.get(cmd_id)
    if not cmd:
        raise ValueError(f"unknown command {cmd_id}")
    site = find_build_site(source)
    return cmd.gen(values, site)


def catalog() -> list[dict]:
    return [c.to_dict() for c in COMMANDS.values()]
