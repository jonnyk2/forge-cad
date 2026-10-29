# Forge — AI-native parametric CAD for making real parts

*Design spec, v0.1 — written by Claude for Claude, with a human-operable front end.*

## 1. Why this exists

Fusion 360 and its peers are built around a mouse: you pick a face, drag a
sketch, click a feature. The parametric history exists, but it is a *recording
of clicks*, and the API mirrors the UI — you can automate what the UI can do,
and almost nothing it can't. For an AI that has no mouse, no eyes, and
unlimited patience for text, that is exactly backwards.

Forge inverts the model:

| Fusion 360 | Forge |
|---|---|
| Model is a binary document; history is a timeline of UI operations | Model **is** a Python file. The file is the only source of truth. |
| Parameters live in a dialog | Parameters are a typed dataclass at the top of the file |
| You judge geometry by looking at it | Every build returns a **measurement report**; checkers return **violations** |
| Manufacturing happens in a separate CAM workspace later | Manufacturing constraints are first-class inputs to the model (`for_fdm(nozzle=0.4)`) |
| API = thin wrapper over UI | API = the whole program; UI = thin wrapper over the API |

The three jobs, in priority order:

1. **Let the AI work at full strength.** Full Python, a real B-rep kernel, and
   a tight *build → measure → check → fix* loop with no human in it.
2. **Make parts that actually come off an FDM printer** (then a CNC mill).
3. **Let a human operate it without the AI** — from a blank part, or by
   tweaking what the AI made.

## 2. Non-goals (for now)

- Not a surfacing/freeform/sculpt tool. B-rep solids with sketches, features,
  booleans, fillets, patterns. That covers ~95% of printed and machined parts.
- Not a slicer. We export clean 3MF/STL and tell you *why* it will or won't
  print; PrusaSlicer/Cura/Bambu do the toolpaths.
- Not a CAM package in v1. CNC phase adds machinability checks and DXF/STEP
  output for Fusion/FreeCAD CAM; toolpath generation comes later if at all.
- Not an assembly/PLM system. Multi-body parts and simple mates only.

## 3. Kernel decision

**OpenCascade (OCCT) via build123d.** Reasons:

- Real B-rep: exact cylinders, true fillets, STEP export that other CAD can edit.
  Mesh kernels (OpenSCAD/Manifold) are fast but you can't fillet them well or
  hand them to a machinist.
- build123d is Pythonic, actively maintained, has selectors
  (`faces().sort_by(Axis.Z)[-1]`) that read like prose — important for an AI
  writing code it can't see run.
- Zero kernel work for us. Our value is the layer above.

Trade-off accepted: OCCT fillets and booleans occasionally fail on odd
geometry. Forge wraps every operation so a failure returns a *diagnosable
error* (which edges, which op) instead of a stack trace.

## 4. The part file

A part is one `.py` file with a fixed, tiny contract:

```python
from forge import *

class Params(ParamSet):
    """Phone stand."""
    width:      mm = Param(70,  min=40, max=120, step=1,  doc="Overall width")
    angle:      deg = Param(65, min=45, max=80,  step=1,  doc="Screen angle")
    wall:       mm = Param(3.0, min=1.6, max=6, step=0.4, doc="Wall thickness")
    lip_height: mm = Param(12,  min=6,  max=25, step=1)
    charger_slot: bool = Param(True, doc="Cutout for a charging cable")

MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PLA")

def build(p: Params) -> Part:
    with BuildPart() as stand:
        ...
    return stand.part
```

Rules:

- **`Params` is the UI.** The human web app reads the dataclass and renders
  sliders/toggles with the declared ranges. No separate schema to keep in sync.
- **`build()` is pure.** Same params in → same geometry out. No global state,
  no file I/O, no randomness. That's what makes rebuild-on-slider-drag safe.
- **`MANUFACTURING` declares intent.** Checkers use it; features use it
  (e.g. `hole(d=3, fit="clearance")` adds FDM horizontal-hole compensation
  automatically when `MANUFACTURING` is FDM).
- Everything in the file is normal Python. The AI can define helpers, loop,
  use `math`, import other parts. No DSL ceiling.

A *project* is a folder of part files plus an optional `assembly.py` and an
`out/` folder for exports. Git-friendly by construction.

## 5. The feedback loop (the actual product)

`forge.inspect(part)` returns a `Report`:

```
bbox:           70.0 × 48.2 × 61.0 mm
volume:         18 432 mm³  (~22.9 g PLA at 100% / ~9.1 g at 20% infill)
surface area:   12 870 mm²
bodies:         1  (solid, watertight)
faces/edges:    38 / 92
center of mass: (35.0, 21.4, 19.8)
footprint:      70.0 × 48.2 mm on Z-min plane, 3 374 mm² contact
thinnest wall:  2.4 mm  @ (12.0, 3.1, 40.2)   [region: lip]
smallest hole:  Ø3.2 mm (×2)
tallest overhang: 58° from vertical @ ...
```

`forge.check(part, MANUFACTURING)` returns `[Violation]`, each with severity,
location, the rule that fired, and a *suggested fix in Params terms* where
possible:

```
ERROR  wall_too_thin     wall at (12.0,3.1,40.2) is 0.9 mm; FDM/0.4 needs ≥ 0.8 mm
                          for one perimeter, ≥ 1.6 mm for a load-bearing wall.
                          Try: wall ≥ 1.6
WARN   overhang          face at z=40–48 slopes 62° from vertical (limit 45°+margin)
                          Try: chamfer the underside, or reorient (flat face is 70×48).
WARN   small_hole_fit    Ø3.2 hole for M3 clearance will print ~Ø2.9 horizontally.
                          Try: hole(fit="clearance") to auto-compensate.
INFO   bridge            4.0 mm bridge at z=30 — fine for most printers.
```

Renders: `forge.render(part)` produces PNGs (iso, front, top, right, and a
section) and an SVG line drawing. The AI reads the PNGs; the human sees the
live 3D view.

Every tool returns **both** human text and a JSON structure. The MCP server
and the web app consume the same objects.

## 6. FDM rules (phase 1)

Parameterized by nozzle `n`, layer height `l`, material class.

| Rule | Default threshold | Severity |
|---|---|---|
| Wall thickness | `< 2n` error, `< 4n` warn for structural walls | error/warn |
| Overhang angle | `> 45°` from vertical warn, `> 60°` error (no supports mode) | warn/error |
| Unsupported bridge | `> 10 mm` warn, `> 25 mm` error | warn/error |
| Vertical hole shrink | holes < Ø10 print ~0.2–0.4 undersize | info + auto-compensate |
| Horizontal hole sag | top of round holes sags; suggest teardrop above Ø6 | warn |
| Small feature | pillars/pins `< 3n` wide | warn |
| Minimum first-layer footprint | contact area `< 100 mm²` or aspect `> 5:1` → tip-over risk | warn |
| Not watertight / multiple bodies | | error |
| Text / emboss depth | `< l` won't show | warn |
| Fit presets | press / snug / sliding / loose clearance tables per nozzle | helper |
| Orientation advisor | ranks the 6 axis orientations + flat faces by (overhang area, height, footprint, layer-line direction vs. load hint) | tool |

Each rule is a plain function in `forge/dfm/fdm.py`, registered in a list, so
the AI can add rules in one place.

## 7. CNC rules (phase 2 — designed now, built later)

`CNC(axes=3, tools=[EndMill(d=6, flute_len=20), EndMill(d=3, ...), Drill(...)])`

- Internal vertical corners need radius ≥ smallest end-mill radius (or dog-bone).
- Pocket depth vs. tool flute length / stickout.
- Undercuts impossible in 3-axis; flag faces not reachable from ±Z (or from
  a declared set of setups).
- Thin walls/floors vs. chatter heuristics.
- Standard drill sizes; tap drill tables.
- Stock + setup planner: suggests setups, outputs per-setup STEP + DXF.

## 8. Human operation without the AI

A local web app (`forge serve`), nothing to install beyond Python:

- **3D viewer** (Three.js, in-browser) with orbit/section/measure.
- **Parameter panel** generated from `Params`: sliders, numbers, toggles,
  enums; live rebuild with debounce; undo stack of param states.
- **Code editor** (CodeMirror) for the part file, with a *Build* button and
  errors mapped to lines. Tweaking by hand = editing the file; the panel and
  the code stay in sync because the file is the truth.
- **Checks panel**: violations list; clicking one highlights the location.
- **Starters**: a library of templates (box with lid, bracket, bushing, gear,
  knob, enclosure, hook, spacer, clip…) you can open and edit — that's "from
  scratch" for most people. A blank template too.
- **Export**: STL / 3MF / STEP / SVG / PNG with one click; file names carry
  the param hash so you know which version you printed.
- Optional AI panel later; not required for anything above.

The web app only ever calls the same Python API the MCP server exposes.

## 9. AI operation

MCP server (`forge mcp`) exposing:

- `list_parts`, `read_part`, `write_part` (full file), `patch_part` (search/replace)
- `build(part, params?)` → report + violations + render paths in one call
- `inspect`, `check`, `render(views)`, `section(plane)`
- `measure(query)` — distance between faces, hole diameters, angles, by selector
- `export(format)`
- `starters` — list/read templates
- `library` — standard dims: screws, nuts, heat-set inserts, bearings, magnets

Design principle: **one call = one full iteration.** The AI should never
need three round-trips to learn whether its change worked.

## 10. Repo layout

```
forge/
  forge/
    __init__.py        # public API re-exports (build123d * + forge helpers)
    params.py          # Param, ParamSet, units
    part.py            # load_part(), build_part(), Part wrapper
    inspect.py         # geometry measurement → Report
    dfm/
      base.py          # Violation, Rule registry, Manufacturing base
      fdm.py           # FDM rules
      cnc.py           # CNC rules (phase 2)
    features.py        # hole(fit=), heatset_boss(), teardrop(), chamfer_underside() ...
    library.py         # fastener/insert/bearing dimension tables
    render.py          # PNG/SVG renders, section views
    export.py          # STL/3MF/STEP/SVG, param-hash naming
    mcp_server.py      # MCP tools
    web/
      app.py           # FastAPI/Flask server
      static/          # viewer + editor (single page)
  starters/            # template parts
  examples/            # worked parts used as tests
  tests/
  SPEC.md  README.md  pyproject.toml
```

## 11. Milestones

1. **Kernel up**: build123d builds a part, exports STL/STEP, in this env.
2. **Core**: params, build, inspect, FDM checks, export. CLI: `forge build part.py`.
3. **MCP**: Claude drives it end to end on three example parts.
4. **Web UI**: human builds a box-with-lid from a starter, tweaks, exports.
5. **Hardening**: 10+ parts, fillet/boolean failure diagnostics, orientation advisor.
6. **CNC phase**.
