"""Geometry tests: need build123d.  Run `pytest -m kernel` once it's installed."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
pytestmark = pytest.mark.kernel

ROOT = pathlib.Path(__file__).resolve().parents[1]
STARTERS = sorted((ROOT / "starters").glob("*.py"))


@pytest.mark.parametrize("path", STARTERS, ids=[p.stem for p in STARTERS])
def test_starter_builds(path, tmp_path):
    from forge import build_part, export, load_part
    pm = load_part(path)
    built = build_part(pm)
    assert built.report.n_solids >= 1
    assert built.report.valid
    assert built.report.volume > 1
    assert not built.errors, "\n".join(str(v) for v in built.errors)
    written = export(built, ["stl", "step"], tmp_path)
    for f in written.values():
        assert pathlib.Path(f).stat().st_size > 100


def test_inspect_box_walls():
    from forge import Align, Axis, Box, BuildPart, Mode, offset, inspect
    with BuildPart() as p:
        Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
        offset(amount=-1.2, openings=p.faces().sort_by(Axis.Z)[-1])
    r = inspect(p.part)
    assert abs(r.size[0] - 40) < 1e-6 and abs(r.size[2] - 20) < 1e-6
    assert r.thinnest is not None and abs(r.thinnest.thickness - 1.2) < 0.05
    assert abs(r.footprint_area - 40 * 30) < 1e-3


def test_inspect_holes_and_overhang():
    from forge import Align, Axis, Box, BuildPart, Cylinder, Mode, Locations, Plane, inspect
    with BuildPart() as p:
        Box(40, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, 10)):
            Cylinder(2.5, 10, mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.MAX))
        # a shelf sticking out: flat underside at z=5
        with Locations((30, 0, 7.5)):
            Box(20, 20, 5)
    r = inspect(p.part)
    assert r.holes and abs(r.holes[0].diameter - 5.0) < 1e-3
    assert any(o.flat and o.span and o.span >= 9.9 for o in r.overhangs)


def test_fdm_checks_fire_on_bad_part():
    from forge import Align, Box, BuildPart, FDM, build_part, load_part
    src = '''
from forge import *
MANUFACTURING = FDM()
def build(p):
    with BuildPart() as b:
        Box(30, 30, 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, 2)):
            Box(0.5, 20, 15, align=(Align.CENTER, Align.CENTER, Align.MIN))   # 0.5 mm fin
    return b.part
'''
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "fin.py").write_text(src)
    built = build_part(load_part(d / "fin.py"))
    assert any(v.rule == "wall_too_thin" for v in built.violations)


def test_fit_diameter_fdm():
    from forge import fit_diameter, screw_diameter, FDM
    from forge import features
    features.set_process(FDM())
    assert fit_diameter(5, "sliding") == pytest.approx(5.5, abs=0.01)   # 5 + 0.2 fit + 0.3 shrink
    assert screw_diameter("M3", "clearance") == pytest.approx(3.7, abs=0.01)  # 3.4 + 0.3
    assert screw_diameter("M3", "heatset") == pytest.approx(4.0, abs=0.01)


def test_viewer_payload_and_selectors():
    from forge import Align, Axis, Box, BuildPart, Cylinder, Locations, Mode, load_part, build_part
    from forge import topology as T
    with BuildPart() as p:
        Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((10, 0, 10)):
            Cylinder(3, 10, mode=Mode.SUBTRACT)
    shape = p.part
    topo = T.viewer_payload(shape)
    assert len(topo["faces"]) == len(list(shape.faces()))
    assert sum(f["tri_count"] for f in topo["faces"]) * 3 == len(topo["indices"])
    assert len(topo["polylines"]) == len(topo["edges"])
    # top face → stable selector
    top_idx = max(range(len(topo["faces"])), key=lambda i: topo["faces"][i]["center"][2] if topo["faces"][i]["type"] == "plane" else -1)
    sel = T.resolve_selector(shape, "faces", top_idx, "part")
    assert sel["stable"] and "sort_by(Axis.Z)[-1]" in sel["expr"]
    # the hole's cylindrical face
    cyl_idx = next(i for i, f in enumerate(topo["faces"]) if f["type"] == "cylinder")
    sel = T.resolve_selector(shape, "faces", cyl_idx, "part")
    assert sel["stable"] and "CYLINDER" in sel["expr"]


def test_command_preview_apply_roundtrip(tmp_path):
    import shutil
    from forge import commands as C, load_part, build_part
    src = (ROOT / "starters" / "blank.py").read_text()
    part = tmp_path / "plate.py"
    part.write_text(src)
    for cmd, vals in [
        ("hole", {"kind": "counterbore", "screw": "M4", "pattern": "grid 2x2", "spacing_x": 30, "spacing_y": 20}),
        ("extrude", {"shape": "Circle", "size_a": 12, "distance": 8, "op": "join", "on": ["part.faces().sort_by(Axis.Z)[-1]"]}),
        ("fillet", {"edges": ["part.edges().filter_by(Axis.Z)"], "radius": 2}),
        ("chamfer", {"edges": ["part.faces().sort_by(Axis.Z)[0].edges()"], "length": 0.4}),
        ("box", {"x": 10, "y": 10, "z": 5, "px": 20, "py": 10, "pz": 4}),
        ("move", {"dz": 2, "rz": 10}),
        ("mirror", {"plane": "Plane.YZ"}),
    ]:
        s = part.read_text()
        code = C.generate(cmd, vals, s)
        new, a, b = C.insert_into_build(s, code)
        part.write_text(new)
        built = build_part(load_part(part))
        assert built.report.n_solids >= 1 and built.report.valid, cmd
