"""Kernel-free tests: parameter schema, coercion, hashing, FDM rules on synthetic reports."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from forge.params import Param, ParamSet
from forge.dfm.base import FDM, CNC, EndMill, run_rules
from forge.inspect import Report, ThinSpot, Hole, Overhang


class P(ParamSet):
    width: float = Param(60, min=10, max=200, step=1, doc="w")
    n: int = Param(4, min=1, max=10)
    hollow: bool = Param(True)
    style: str = Param("round", choices=["round", "square"])


def test_defaults_and_specs():
    p = P()
    assert p.width == 60 and p.n == 4 and p.hollow is True and p.style == "round"
    names = [s["name"] for s in P.specs()]
    assert names == ["width", "n", "hollow", "style"]
    assert P.specs()[0]["kind"] == "float"
    assert P.specs()[1]["kind"] == "int"
    assert P.specs()[2]["kind"] == "bool"
    assert P.specs()[3]["kind"] == "choice"


def test_coercion_and_limits():
    p = P(width="80", n="3.6", hollow="false", style="square")
    assert p.width == 80.0 and p.n == 4 and p.hollow is False and p.style == "square"
    with pytest.raises(ValueError):
        P(width=500)
    with pytest.raises(ValueError):
        P(style="hex")
    with pytest.raises(ValueError):
        P(bogus=1)


def test_hash_stable():
    assert P().hash() == P().hash()
    assert P(width=61).hash() != P().hash()


def test_cli_parse():
    p = P.from_cli(["--width", "70", "n=2", "--hollow"])
    assert p.width == 70 and p.n == 2 and p.hollow is True


def _report(**kw):
    base = dict(bbox_min=(0, 0, 0), bbox_max=(50, 40, 30), size=(50, 40, 30), volume=20000, area=8000,
                center_of_mass=(25, 20, 15), n_solids=1, n_faces=10, n_edges=24, valid=True,
                footprint_area=2000, footprint_size=(50, 40), thin_spots=[], holes=[], overhangs=[])
    base.update(kw)
    return Report(**base)


def test_fdm_wall_rules():
    r = _report(thin_spots=[ThinSpot(0.5, (1, 1, 1), (1, 0, 0)), ThinSpot(1.2, (2, 2, 2), (1, 0, 0))])
    vs = run_rules(r, None, FDM())
    rules = {v.rule: v.severity for v in vs}
    assert rules["wall_too_thin"] == "error"
    assert "wall_thin" in rules


def test_fdm_overhang_and_bridge():
    r = _report(overhangs=[Overhang(70, 100, (1, 1, 10), 8, 12, False),
                            Overhang(90, 200, (5, 5, 10), 10, 10, True, span=30)])
    vs = run_rules(r, None, FDM())
    sev = {v.rule: v.severity for v in vs}
    assert sev["overhang"] == "error"
    assert sev["unsupported_ceiling"] == "error"
    vs2 = run_rules(r, None, FDM(supports=True))
    assert {v.rule: v.severity for v in vs2}["overhang"] == "info"


def test_fdm_holes_and_bed():
    r = _report(holes=[Hole(3.0, (0, 0, 1), (1, 1, 1), 5), Hole(8.0, (1, 0, 0), (2, 2, 2), 10)],
                size=(300, 40, 30))
    vs = run_rules(r, None, FDM())
    rules = {v.rule for v in vs}
    assert "hole_shrink" in rules and "horizontal_hole_sag" in rules and "too_big" in rules


def test_cnc_corner_radius():
    r = _report(holes=[Hole(2.0, (0, 0, 1), (1, 1, 1), 5)])
    vs = run_rules(r, None, CNC(tools=[EndMill(6)]))
    assert any(v.rule == "corner_radius_too_small" and v.severity == "error" for v in vs)


def test_report_summary_runs():
    s = _report(thin_spots=[ThinSpot(1.0, (1, 1, 1), (1, 0, 0))]).summary()
    assert "thinnest wall" in s
