# Writing forge parts

A part is one Python file.  The file **is** the model.

## Contract

```python
"""One-line description shown in lists.  Longer notes below."""
from forge import *

class Params(ParamSet):
    width:  mm   = Param(60, min=20, max=200, step=1, doc="Outer width")
    height: mm   = Param(30, min=5,  max=100, step=1)
    wall:   mm   = Param(2.4, min=0.8, max=8, step=0.4, doc="Wall thickness")
    lid:    bool = Param(True, doc="Model the lid too")
    style:  str  = Param("rounded", choices=["rounded", "square"])

MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PLA")   # or CNC(tools=[EndMill(6), EndMill(3)])

def build(p: Params):
    with BuildPart() as part:
        Box(p.width, p.width, p.height)
        ...
    return part.part
```

Rules:
1. `Params` is the entire UI: declare `min`/`max`/`step`/`doc` and the web app gets sliders.
2. `build(p)` must be **pure** (no files, no globals, no randomness) and return a `Part`/`Solid`
   (`builder.part`), or a list of them for multi-body.
3. Put the part so it sits on the bed: Z-min is the print bed.  `Box(...)` is centred — use
   `align=(Align.CENTER, Align.CENTER, Align.MIN)` or translate.  The checks assume +Z is up.
4. Millimetres and degrees everywhere.
5. Make every hole with a forge helper so it's sized for the real process.

## Loop

`build` → read the report + violations → fix the code → `build` again.  Export when clean
(warnings are allowed if you've judged them).  Run `orient` before adding supports or redesigning.

## FDM design rules (what the checker enforces, nozzle n = 0.4, layer l = 0.2)

| Thing | Rule | Why / fix |
|---|---|---|
| Walls | ≥ 2n (0.8) absolute, ≥ 4n (1.6) for anything load-bearing; ideally a multiple of 2n | perimeters fill it exactly |
| Overhangs | ≤ 45° from vertical fine; 45–60° rough; > 60° fails | chamfer 45° under it, or reorient |
| Bridges | ≤ 10 mm fine, ≤ 25 mm needs tuning, more = support | arch or chamfer under, or split |
| Vertical holes | print 0.1–0.3 mm undersize | `screw_hole()` / `pin_hole()` compensate |
| Horizontal holes | top sags above Ø6 | `teardrop_hole()` or orient axis vertical |
| Pins / posts | ≥ 4n (1.6) wide, prefer ≥ 3 | thin posts snap along layer lines |
| Text | emboss ≥ 3l deep, stroke ≥ 1.5n | `text_depth()` |
| First layer | footprint ≥ 100 mm², height/width ≤ 5 | brim, or lay flat |
| Bottom edges | 0.4 mm chamfer | elephant foot; `elephant_foot_chamfer(part)` |
| Fillets | fillet *vertical* edges freely; on top edges fine; on bottom edges use chamfer | bottom fillets create tiny overhangs |
| Layer lines | load should be *across* layers, not pulling them apart | orient so the weak axis isn't Z |
| Snap fits | hook thickness ≥ 1.2, taper 30°, travel ≤ 1/3 beam | PLA is brittle; PETG snaps better |
| Threads | ≥ M8 printable; below that use heat-set inserts or nuts | `heatset_boss()` |
| Tolerances | parts that touch: sliding 0.2, loose 0.4, press −0.1 | `fit_diameter(nominal, fit)` |

## Features (inside a `BuildPart`, at the current `Locations`)

```python
screw_hole("M3")                         # clearance, compensated
screw_hole("M3", kind="tap", depth=8)    # self-tapping into plastic
screw_hole("M3", kind="heatset")         # for a brass insert
screw_hole("M4", counterbore=True)       # recess for socket head
pin_hole(5, fit="sliding")               # Ø5 shaft that turns
pin_hole(8, fit="press", depth=6)        # Ø8 dowel pressed in
magnet_pocket("6x3")                     # 6×3 disc magnet, snug
bearing_pocket("608")                    # 22 mm OD bearing seat
heatset_boss("M3", height=8)             # boss + insert hole, grows +Z from the workplane
teardrop_hole(8, depth=20)               # horizontal hole with a printable top
elephant_foot_chamfer(part.part, 0.4)    # returns a new part
screw("M3")["head_d"]                    # raw tables
fit_diameter(10, "sliding")              # → 10.4 for FDM
```

## build123d essentials (what you need 95% of the time)

```python
with BuildPart() as p:
    Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    Cylinder(5, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))         # adds
    Cylinder(3, 20, align=..., mode=Mode.SUBTRACT)                           # cuts
    top = p.faces().sort_by(Axis.Z)[-1]                                      # select a face
    with Locations(top):                                                     # work on it
        with GridLocations(30, 20, 2, 2):                                    # 2×2 pattern
            screw_hole("M3")
    with BuildSketch(Plane.XZ.offset(-15)) as s:                             # sketch on a plane
        RectangleRounded(20, 8, 2)
    extrude(amount=30, mode=Mode.SUBTRACT)                                   # slot through
    fillet(p.edges().filter_by(Axis.Z), radius=3)                            # round vertical edges
    chamfer(p.faces().sort_by(Axis.Z)[0].edges(), length=0.4)               # elephant foot
    offset(amount=-2, openings=top)                                          # hollow out → box with open top
    mirror(about=Plane.YZ)                                                   # symmetric copy
    with PolarLocations(20, 6): Cylinder(2, 5)                               # 6 pins on a circle
result = p.part
```

Selectors: `.faces()/.edges()/.vertices()` then `.sort_by(Axis.Z)`, `.filter_by(Axis.Z)`,
`.filter_by(GeomType.CYLINDER)`, `.group_by(Axis.Z)[-1]`, `[0]`/`[-1]`.
Planes: `Plane.XY` (floor), `Plane.XZ` (front), `Plane.YZ` (side), `Plane.XY.offset(10)`,
`Plane(origin, z_dir)`, or a face: `Plane(top)`.

Booleans: `Mode.ADD` (default), `Mode.SUBTRACT`, `Mode.INTERSECT`.  Sweep/loft/revolve:
`sweep(path=...)`, `loft()`, `revolve(axis=Axis.Z)`.

Sketch primitives: `Rectangle`, `RectangleRounded`, `Circle`, `Ellipse`, `Polygon`,
`RegularPolygon`, `SlotCenterToCenter`, `Text("Hi", font_size=8)`, `Trapezoid`.

## When OpenCascade fails

`fillet` on edges that meet at a tangent, or whose radius exceeds half the adjacent face,
is the #1 failure.  Fix: smaller radius, fillet fewer edges at once (vertical edges first,
then top), or chamfer instead.  Booleans fail on coincident faces: overlap by 0.01 mm.

## Multi-part projects

Put shared helpers in `_common.py` (underscore = not a part).  `from _common import *`.
A lid and a box are two part files that import the same `Params`-like dims from `_common`.
