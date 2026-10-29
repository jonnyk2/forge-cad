"""Manufacturing-aware features.

These are thin wrappers over build123d that bake in what you'd otherwise
have to remember: hole-shrink compensation, fit allowances, insert sizes,
teardrops for horizontal holes, elephant-foot chamfers.  Use them inside a
``BuildPart`` block exactly like build123d's own ``Hole``.

    with BuildPart() as p:
        Box(40, 30, 10)
        with Locations(p.faces().sort_by(Axis.Z)[-1]):
            with GridLocations(30, 20, 2, 2):
                screw_hole("M3", fit="clearance")       # compensated Ø3.4-ish

The current process is taken from ``forge.process.current()`` which the part
loader sets from the part file's ``MANUFACTURING`` constant.
"""
from __future__ import annotations

import math
from typing import Optional

from build123d import (
    Align, Axis, BuildPart, BuildSketch, Circle, Cylinder, Hole, Location,
    Locations, Mode, Plane, Polygon, Rectangle, Rot, extrude, chamfer,
)

from . import library
from .dfm.base import FDM, Manufacturing

# --------------------------------------------------------------------------
# current process (set by the part loader)
# --------------------------------------------------------------------------
_CURRENT: Manufacturing = FDM()


def set_process(p: Manufacturing) -> None:
    global _CURRENT
    _CURRENT = p


def current() -> Manufacturing:
    return _CURRENT


# --------------------------------------------------------------------------
# diameters
# --------------------------------------------------------------------------

def fit_diameter(nominal: float, fit: str = "sliding", process: Optional[Manufacturing] = None,
                 vertical: bool = True) -> float:
    """Hole diameter that will *actually* produce the requested fit for a
    pin/shaft of `nominal` diameter once manufactured.

    fit: press | snug | sliding | loose | magnet | bearing
    """
    p = process or current()
    d = nominal
    if isinstance(p, FDM):
        d += library.FDM_FITS[fit]
        if vertical:
            d += p.hole_compensation(nominal)
        else:
            d += p.hole_compensation(nominal) * 0.5   # horizontal holes shrink less in XY
    else:
        # machined: standard-ish allowances
        d += {"press": -0.02, "snug": 0.01, "sliding": 0.05, "loose": 0.2,
              "magnet": 0.05, "bearing": 0.0}[fit]
    return round(d, 2)


def screw_diameter(size: str, kind: str = "clearance", process: Optional[Manufacturing] = None) -> float:
    """kind: clearance | close | loose | tap | heatset"""
    p = process or current()
    s = library.screw(size)
    if kind == "heatset":
        d = library.heatset(size)["hole"]
    elif kind == "tap":
        d = s["tap"]
        if isinstance(p, FDM):
            d += 0.1   # thread-forming screws into plastic: a touch larger than the metal tap drill
    else:
        d = s[{"clearance": "normal"}.get(kind, kind)]
    if isinstance(p, FDM) and kind != "heatset":
        d += p.hole_compensation(d)
    return round(d, 2)


# --------------------------------------------------------------------------
# builder-mode features
# --------------------------------------------------------------------------

def screw_hole(size: str = "M3", kind: str = "clearance", depth: Optional[float] = None,
               counterbore: bool = False, countersink: bool = False, head_clearance: float = 0.4):
    """A hole sized for a metric screw, compensated for the current process.

    kind: clearance (default) | close | loose | tap | heatset
    counterbore: recess for a socket-head cap screw head
    Must be called inside BuildPart with active Locations.
    """
    s = library.screw(size)
    d = screw_diameter(size, kind)
    if counterbore:
        from build123d import CounterBoreHole
        return CounterBoreHole(radius=d / 2, counter_bore_radius=(s["head_d"] + head_clearance) / 2,
                               counter_bore_depth=s["head_h"] + 0.2, depth=depth)
    if countersink:
        from build123d import CounterSinkHole
        return CounterSinkHole(radius=d / 2, counter_sink_radius=(s["head_d"] + head_clearance) / 2, depth=depth)
    return Hole(radius=d / 2, depth=depth)


def pin_hole(nominal: float, fit: str = "sliding", depth: Optional[float] = None, vertical: bool = True):
    """Hole for a pin/shaft/magnet/bearing of `nominal` OD with the requested fit."""
    return Hole(radius=fit_diameter(nominal, fit, vertical=vertical) / 2, depth=depth)


def magnet_pocket(spec: str = "6x3", extra_depth: float = 0.2):
    m = library.magnet(spec)
    return Hole(radius=fit_diameter(m["diameter"], "magnet") / 2, depth=m["thickness"] + extra_depth)


def bearing_pocket(number: str = "608", depth: Optional[float] = None):
    b = library.bearing(number)
    return Hole(radius=fit_diameter(b["od"], "bearing") / 2, depth=depth or b["width"])


def heatset_boss(size: str = "M3", height: float = 8.0, extra_od: float = 0.0):
    """A standing boss with a heat-set insert hole in the top.  Place with
    Locations on the face the boss should stand on (boss grows along +Z of
    that workplane)."""
    h = library.heatset(size)
    od = h["boss_od"] + extra_od
    boss = Cylinder(od / 2, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((0, 0, height)):
        Hole(radius=h["hole"] / 2, depth=min(height - 1.0, h["depth"] + 0.5))
    return boss


def teardrop_hole(diameter: float, depth: float, fit: str = "sliding", up=(0, 0, 1)):
    """Horizontal hole with a 45° teardrop top so it prints without sagging.

    Call inside BuildPart with a Locations/workplane whose normal is the hole
    axis (e.g. ``Plane.XZ`` for a hole along Y).  `up` is the world up vector,
    used to point the teardrop's apex upward.
    """
    d = fit_diameter(diameter, fit, vertical=False)
    r = d / 2
    ctx = BuildPart._get_context()
    plane = ctx.workplanes[0] if ctx is not None and ctx.workplanes else Plane.XY
    # express world up in the sketch plane
    from build123d import Vector
    up_local = plane.to_local_coords(Vector(up))
    ang = math.degrees(math.atan2(up_local.Y, up_local.X)) - 90
    a = r / math.sqrt(2)
    c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    rot2 = lambda x, y: (x * c - y * s_, x * s_ + y * c)
    with BuildSketch(plane) as sk:
        Circle(r)
        Polygon(rot2(-a, a), rot2(a, a), rot2(0, r * math.sqrt(2)), align=None)
    return extrude(sk.sketch, amount=-depth, mode=Mode.SUBTRACT)


def elephant_foot_chamfer(part, size: float = 0.4):
    """Chamfer the bottom outside edges so the first-layer squish doesn't
    make the part wider than designed.  Returns the modified part."""
    bottom = part.faces().sort_by(Axis.Z)[0]
    try:
        return part.chamfer(size, None, list(bottom.edges()))
    except Exception:
        return part


def text_depth(process: Optional[Manufacturing] = None) -> float:
    """Depth that embossed/engraved text should have to survive the process."""
    p = process or current()
    if isinstance(p, FDM):
        return max(0.6, p.layer * 3)
    return 0.5
