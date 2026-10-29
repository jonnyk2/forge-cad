"""CNC (3-axis milling) rules — phase 2 skeleton.

The first rules that are cheap and high value are here now; the rest of the
design is in SPEC.md §7.
"""
from __future__ import annotations

import math

from build123d import GeomType
from OCP.BRepAdaptor import BRepAdaptor_Surface

from .base import CNC, Violation


def internal_corner_radius(report, shape, p: CNC):
    """Concave vertical cylindrical faces (inside corners / pockets) need a
    radius at least as big as the smallest end mill."""
    out = []
    r_tool = p.smallest_tool.diameter / 2
    for h in report.holes:            # inspect() already found concave cylinders
        if abs(h.axis_dir[2]) < 0.99:
            continue
        r = h.diameter / 2
        if r < r_tool - 1e-3:
            out.append(Violation("corner_radius_too_small", "error",
                                 f"internal radius {r:.2f} mm is smaller than the smallest end mill radius {r_tool:.2f} mm",
                                 location=h.center, value=r, limit=r_tool,
                                 fix=f"use radius ≥ {r_tool:.2f} mm, or add a dog-bone relief"))
    return out


def sharp_internal_corners(report, shape, p: CNC):
    """Vertical edges where two planar faces meet at a concave angle: a 3-axis
    mill cannot make a sharp inside corner."""
    out = []
    n = 0
    for e in shape.edges():
        try:
            if e.geom_type != GeomType.LINE:
                continue
            d = e % 0.5  # tangent direction
            if abs(d.Z) < 0.99:
                continue
            faces = [f for f in shape.faces() if any(ee.is_same(e) for ee in f.edges())]
            if len(faces) != 2 or any(f.geom_type != GeomType.PLANE for f in faces):
                continue
            n1, n2 = faces[0].normal_at(), faces[1].normal_at()
            mid = e @ 0.5
            # concave if the point slightly along (n1+n2) is inside the solid
            probe = mid + (n1 + n2).normalized() * 0.2
            from ..inspect import _point_inside
            if _point_inside(shape, probe):
                out.append(Violation("sharp_inside_corner", "error",
                                     "sharp vertical inside corner; an end mill leaves a radius here",
                                     location=(mid.X, mid.Y, mid.Z),
                                     fix=f"fillet with radius ≥ {p.smallest_tool.diameter/2:.2f} mm or add a dog-bone"))
                n += 1
                if n >= 10:
                    break
        except Exception:
            continue
    return out


def pocket_depth(report, shape, p: CNC):
    out = []
    for h in report.holes:
        if abs(h.axis_dir[2]) < 0.99:
            continue
        r = h.diameter / 2
        tool = min((t for t in p.tools if t.diameter / 2 <= r + 1e-3), key=lambda t: -t.diameter, default=None)
        if tool is None:
            continue
        if h.length > tool.flute_length * 1.0:
            out.append(Violation("deep_pocket", "warn",
                                 f"{h.length:.1f} mm deep feature of Ø{h.diameter:g}; largest fitting tool Ø{tool.diameter:g} has {tool.flute_length:.0f} mm flutes",
                                 location=h.center, value=h.length, limit=tool.flute_length,
                                 fix="reduce depth, enlarge the pocket for a bigger tool, or machine from both sides"))
    return out


def undercuts_3axis(report, shape, p: CNC):
    """Faces not visible from +Z or -Z can't be cut in a single 3-axis setup pair."""
    if p.axes != 3:
        return []
    out = []
    n = 0
    for o in report.overhangs:
        # overhangs are downward faces not on the bed; in a 2-setup (top/bottom)
        # world they are reachable from -Z unless something is below them.
        pass
    return out


def thin_walls(report, shape, p: CNC):
    out = []
    for t in report.thin_spots[:6]:
        if t.thickness < p.min_wall:
            out.append(Violation("wall_too_thin", "warn",
                                 f"wall is {t.thickness:.2f} mm; thin walls chatter and deflect when milled (≥ {p.min_wall} mm recommended for {p.material})",
                                 location=tuple(round(c, 2) for c in t.location), value=t.thickness, limit=p.min_wall))
    return out


RULES = [internal_corner_radius, sharp_internal_corners, pocket_depth, thin_walls]
