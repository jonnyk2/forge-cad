# Forge vs. Fusion 360 — feature and UI gap analysis

*Sources: Autodesk's own command inventory (Edit-in-Place supported-commands page), the Fusion
UI navigation guide, the sketch-constraints reference and the Fusion API reference. No
reverse-engineering was needed or used: Autodesk documents every command publicly.*

Legend: ✅ have · 🟡 partial / library has it but no UI · ❌ missing · ➖ deliberately out of scope

## 1. The UI shell (how you navigate)

| Fusion element | What it does | Forge today | Plan |
|---|---|---|---|
| **Canvas** with click-to-select faces/edges/bodies | Pick geometry, see it highlight, feed it to commands | ❌ viewer is look-only (orbit, measure two points) | **P1** Pick faces/edges/vertices; highlight; show what you picked (area, normal, length, Ø) and the *selector expression* that names it in code |
| **ViewCube** | Jump to standard/iso views, orbit by dragging | 🟡 four view buttons | **P1** Real view cube widget, home view, orthographic/perspective toggle |
| **Navigation bar** | Orbit / pan / zoom / fit / display settings | 🟡 orbit only via mouse | **P1** Fit (F), zoom-to-selection, pan/orbit modes, grid on/off, shading modes (shaded, shaded+edges, wireframe, x-ray) |
| **Browser** (tree of components, bodies, sketches, origin, construction, joints) with eye toggles | See and hide what the model is made of | ❌ | **P1** Tree generated from the built result: bodies (with names), origin planes/axes, construction geometry, sketches; visibility and isolate |
| **Timeline** | Ordered features; click to edit; drag to reorder; roll back | ❌ | **P2** The *statements of `build()`* are the timeline. Parse the file, list each feature line; click → highlight the faces it created (diff before/after) and open an edit box; roll-back marker = build up to that line |
| **Marking menu** (right-click) + keyboard shortcuts (E extrude, H hole, F fillet, M move, Q press-pull, L line, C circle, R rectangle, D dimension, S shortcuts box, I measure…) | Fast command access | ❌ | **P1** Right-click menu on selection; Fusion's single-letter shortcuts; **S** command palette with fuzzy search |
| **Toolbar tabs** Solid / Surface / Sheet Metal / Plastic / Utilities, with Create / Modify / Assemble / Construct / Inspect / Insert / Select groups | Where commands live | ❌ (only params + code) | **P1** Toolbar with the same groups; every command is a small dialog that **inserts code** into `build()` (see §3) |
| **Command dialog** with live preview and OK/Cancel | Set extent, direction, operation (join/cut/intersect/new body) | ❌ | **P1** Dialog → preview build in-memory → OK writes the line |
| **Parameters dialog** (user params with expressions, units) | Drive the model | ✅ sliders from `Params` | **P2** Expressions between params (`width = length/2`), units, favourites |
| **Data panel** (projects, versions, cloud) | File management | 🟡 projects folder | **P2** Version history = git log of the part file; restore any version |
| **Display settings** (visual style, environment, effects, ground shadows, section analysis) | Appearance | 🟡 section slider | **P2** Styles; section analysis with cap colour; ground shadow; part appearance/colour |
| **Undo / Redo** | | 🟡 editor undo only | **P1** Model-level undo = file history stack |
| **Comments / version milestones** | collaboration | ➖ | git |

## 2. Commands — Design workspace

### Sketch (Fusion: Create / Modify / Constraints / Palette)

| Fusion | Forge | Plan |
|---|---|---|
| Line, Rectangle (2-pt, 3-pt, centre), Circle (centre, 2-pt, 3-pt, tangent), Arc (3-pt, centre, tangent), Polygon, Ellipse, Slot (5 types), Spline (fit / control point), Conic, Point, Text | 🟡 all exist in build123d (`Line`, `Rectangle`, `RectangleRounded`, `Circle`, `ThreePointArc`, `RegularPolygon`, `Ellipse`, `SlotCenterToCenter`…, `Spline`, `Text`) — no drawing UI | **P2** 2-D sketch mode on a chosen plane: click to draw, dimension with D, generates `BuildSketch` code |
| Fillet, Trim, Extend, Break, Offset, Mirror, Rectangular/Circular pattern, Project/Include, Intersect, Scale, Move/Copy | 🟡 fillet/offset/mirror/patterns exist in library; trim/extend/break are UI-only concepts | **P2** |
| 12 constraints (horizontal/vertical, coincident, tangent, equal, parallel, perpendicular, fix, midpoint, concentric, collinear, symmetry, curvature) + dimensions (linear, aligned, angular, diameter, radius, driven) | ❌ (code-first: positions are explicit expressions) | **P3** Constraint solver is the one piece build123d lacks. Options: (a) keep code-explicit and make the sketch UI emit parametric expressions — covers 90% of printed parts; (b) embed a small 2-D solver (e.g. `solvespace`'s python bindings `py-slvs`) for true constraint sketches. Decide after P2. |

### Solid › Create

| Fusion | Forge library | UI | Notes |
|---|---|---|---|
| New Component | ❌ | ❌ | **P2** components = separate part files or named bodies; assembly file |
| Create Sketch | 🟡 | ❌ | P2 |
| Extrude (distance / to object / all / symmetric / two sides / taper / join-cut-intersect-new) | ✅ `extrude(amount, both, taper, until=Until.NEXT/LAST, mode)` | ❌ | **P1** dialog |
| Revolve (angle / full / to) | ✅ `revolve` | ❌ | P1 |
| Sweep (path, guide rail, twist) | ✅ `sweep` | ❌ | P1 |
| Loft (rails, guides, tangent/smooth) | ✅ `loft` | ❌ | P1 |
| Rib, Web | 🟡 doable with sketch+extrude | ❌ | P3 helper `rib()` |
| Emboss (text/sketch onto curved face) | 🟡 `project` + extrude on planar; curved partial | ❌ | P3 |
| Hole (simple / counterbore / countersink / tapped / clearance, standards) | ✅ `Hole`, `CounterBoreHole`, `CounterSinkHole`, plus forge `screw_hole` with ISO sizes & print compensation | ❌ | **P1** dialog on a picked face |
| Thread (modeled / cosmetic, ISO/ANSI) | 🟡 `IsoThread` exists | ❌ | P2 |
| Box, Sphere, Cylinder, Torus, Coil, Pipe | ✅ `Box Sphere Cylinder Torus` ; coil = `Helix`+sweep; pipe = sweep | ❌ | P1 |
| Rectangular / Circular pattern, Pattern on path | ✅ `GridLocations`, `PolarLocations`, `LocationList` on path | ❌ | P1 |
| Mirror | ✅ `mirror` | ❌ | P1 |
| Thicken, Boundary Fill | 🟡 `thicken`; boundary fill ➖ | | P3 |
| Form (T-spline sculpt) | ➖ | | out of scope (not a 3D-printing-first need) |

### Solid › Modify

| Fusion | Forge library | UI | Notes |
|---|---|---|---|
| Press Pull | 🟡 = extrude / offset face | ❌ | P1 (Q) |
| Fillet (constant, variable, rule, setback) / Chamfer (equal, two-distance, distance-angle) | ✅ `fillet`, `chamfer(length, length2, angle)`; variable ➖ | ❌ | **P1** pick edges → dialog |
| Shell | ✅ `offset(openings=…)` | ❌ | P1 |
| Draft | 🟡 extrude taper only; face draft ➖ | ❌ | P3 |
| Scale | ✅ `scale` | ❌ | P1 |
| Combine (join / cut / intersect, keep tools) | ✅ `Mode.ADD/SUBTRACT/INTERSECT` | ❌ | P1 |
| Offset Face / Replace Face / Split Face / Split Body / Silhouette Split | 🟡 `split(by plane)`; offset face ➖ | ❌ | P2 split body |
| Move / Copy (free, translate, rotate, point-to-point) | ✅ `Location`, `Pos`, `Rot`, `.moved()` | ❌ | P1 |
| Align | 🟡 | ❌ | P2 |
| Delete / Remove features / faces | ✅ edit code | — | timeline delete |
| Physical Material, Appearance | 🟡 `material=` density only | ❌ | P2 appearance colour; materials table |
| Change Parameters | ✅ | ✅ | P2 expressions |
| Compute All | ✅ build | ✅ | |

### Surface / Sheet Metal / Plastic

| Fusion | Forge | Plan |
|---|---|---|
| Surface: Extrude/Revolve/Sweep/Loft/Patch/Offset/Ruled, Trim/Extend/Stitch | 🟡 build123d `BuildSurface`-ish via faces; thin | P3 |
| Sheet Metal: Flange, Bend, Unfold, rules | ❌ | P3 (laser-cut phase — DXF unfold is valuable for makers) |
| Plastic: Boss, Snap fit, Lip, Rest, Vent, Rib | ❌ | **P2** — these are *exactly* what 3D-printed parts need; forge features `heatset_boss`, `snap_fit`, `lip`, `vent`, `rib` |

### Assemble

| Fusion | Forge | Plan |
|---|---|---|
| Components, occurrences | ❌ | P2 multi-part files + `assembly.py` |
| Joints (rigid, revolute, slider, cylindrical, pin-slot, planar, ball), as-built joints, limits, drive, animate | ❌ | P3 — build123d has `RigidJoint`, `RevoluteJoint`, `LinearJoint`, `CylindricalJoint`, `BallJoint`; expose + animate in viewer |
| Rigid group, Ground, Capture position, Interference | ❌ | P3; interference check is cheap (`intersect` volume) — do in P2 |

### Construct

| Fusion | Forge | Plan |
|---|---|---|
| Offset plane, Plane at angle, Tangent plane, Midplane, Plane through 2 edges / 3 points / point on face; Axis through cylinder / perpendicular / two planes / two points / edge; Point at vertex / through 2 edges / 3 planes / centre of circle / along path | ✅ `Plane.XY.offset()`, `Plane(origin, z_dir)`, `Plane(face)`, `Axis`, `Vertex` | ❌ | **P1** Construct menu → code; show them in the browser and canvas |

### Inspect

| Fusion | Forge | Plan |
|---|---|---|
| Measure (point/edge/face, distance, angle, area, Ø, loop length) | 🟡 point-to-point only | **P1** selection-based measure |
| Interference | ❌ | P2 |
| Curvature comb / Zebra / Draft analysis / Accessibility / Minimum radius / Section analysis / Center of mass / Component colour | 🟡 CoM in report; section slider | P2 draft analysis (free: we already compute face angles), min-radius, section with caps |

### Insert / Select / Utilities

| Fusion | Forge | Plan |
|---|---|---|
| Insert SVG / DXF / Mesh (STL/OBJ) / McMaster-Carr / Decal / Canvas (image) / Derive | ❌ | **P2** import STL (mesh → ref body), SVG/DXF → sketch, STEP import; McMaster-Carr-style standard-parts library = our `library.py` expanded |
| Select: window/freeform/paint, select by size, seed & boundary, selection filters, priority | ❌ | P1 filters (faces/edges/vertices/bodies) |
| Utilities: Make (print, 3D print utility), Add-ins/Scripts, Simplify | 🟡 export | P2 "send to slicer" |

### Other workspaces

| Fusion workspace | Forge | Plan |
|---|---|---|
| Drawings (2-D views, dimensions, BOM, title block, PDF/DXF) | 🟡 SVG projection | **P2** auto drawing sheet: 3 views + iso, overall dims, hole table; PDF |
| Manufacture (CAM) | ❌ | P4 — CNC phase: DFM first, then 2.5-D toolpaths via an external engine or export to Fusion/FreeCAD CAM |
| Render / Animation / Simulation / Generative | ➖ | out of scope; render = nicer viewer shading |

## 3. How Forge gets Fusion-style navigation without giving up code-as-truth

The one rule: **the part file stays the only source of truth.** UI commands never
mutate a hidden model; they *write code*. This is exactly how Zoo's KCL gets two-way editing,
and it is what keeps the AI and the human on the same page.

1. **Selection → selector.** Clicking a face in the viewer resolves to a stable build123d
   selector expression (e.g. `part.faces().sort_by(Axis.Z)[-1]`, or `faces().filter_by(GeomType.CYLINDER).sort_by(Axis.X)[2]`),
   chosen by trying candidate expressions against the built shape until exactly one matches.
   The UI shows the expression; commands consume it.
2. **Command dialog → code line.** Extrude dialog with distance 10, operation Cut, on the
   selected sketch/face → inserts `extrude(amount=-10, mode=Mode.SUBTRACT)` (or the full
   `with BuildSketch(Plane(face)): … ; extrude(...)` block) at the cursor / end of `build()`.
   Preview = build a temp copy; OK = write file; the editor shows the new lines highlighted.
3. **Timeline = statements of `build()`.** Python's `ast` gives us every top-level statement
   in `build()` with line numbers. Build the model statement-by-statement (we already
   build fast: 0.1–0.6 s per part) and diff faces to know what each statement created.
   Click a timeline item → highlight its faces, open its args in a mini-dialog; drag to
   reorder = move lines; roll-back marker = truncate the build.
4. **Browser = the built result.** Bodies, faces by type, construction geometry (anything
   assigned to a `Plane`/`Axis` variable in `build()`), sketches (`BuildSketch` blocks).
5. **Names.** `body.label = "lid"` and `plane_top = Plane(...)` give human names in the
   browser; the AI is told to name things.

The AI benefits from every one of these: the timeline diff is exactly the "what did my
last edit change" signal it lacks today, and selectors become a shared vocabulary.

## 4. Phases

| Phase | Scope | Size |
|---|---|---|
| **P1 — Navigate & command (Fusion feel)** | Pick faces/edges/bodies with highlight; selector display; ViewCube + nav bar + shading modes + fit/zoom-to-selection; browser tree with visibility/isolate; toolbar groups + right-click marking menu + single-letter shortcuts + **S** palette; code-writing dialogs for Extrude, Revolve, Sweep, Loft, Hole (ISO), Fillet, Chamfer, Shell, Move/Copy, Mirror, Rect/Circ pattern, Combine, Scale, primitives, Construct plane/axis/point; selection-based Measure; model undo/redo | ~3–4 sessions |
| **P2 — Model like Fusion** | Timeline from `build()` AST with highlight/edit/reorder/rollback; sketch mode (draw + dimension → code); parameters with expressions; plastic features (boss, snap-fit, lip, vent, rib); split body; threads; appearance/colour; section analysis with caps; draft/min-radius analysis; interference; STL/STEP/SVG/DXF import; drawings sheet; git version history; multi-body + components | ~5–6 sessions |
| **P3 — Assemblies & constraints** | Joints with limits + animate; rigid groups; constraint-solved sketches (py-slvs) if P2 shows the need; surfaces; sheet metal unfold → DXF | later |
| **P4 — CNC** | CNC DFM rules complete; setups/stock; 2.5-D toolpaths or hand-off | later |

## 5. What we will not copy

Form (T-splines), Simulation, Generative design, Rendering, Animation workspaces, cloud
data management. Those don't serve "parts that get printed or machined", and each is a product in itself.
