"""Orientation advisor: which way up should this print?

Scores the six axis-aligned orientations (and any large flat face) by
overhang area, support volume proxy, height (print time), footprint stability
and bridges, then returns a ranked list.  The AI calls this before deciding
whether to redesign or just rotate.
"""
from __future__ import annotations

import dataclasses
import math

from build123d import Axis, Location, Shape

from .inspect import inspect

CANDIDATES = {   # (about X, about Y, about Z) degrees
    "as-designed (+Z up)": (0, 0, 0),
    "flip (-Z up)":        (180, 0, 0),
    "+X up":               (0, -90, 0),
    "-X up":               (0, 90, 0),
    "+Y up":               (90, 0, 0),
    "-Y up":               (-90, 0, 0),
}


@dataclasses.dataclass
class Orientation:
    name: str
    rotation: tuple[float, float, float]
    height: float
    footprint_area: float
    overhang_area: float          # mm² of faces beyond the overhang limit (excl. bed)
    steepest: float
    bridge_span: float
    score: float
    notes: list[str]

    def to_dict(self):
        return dataclasses.asdict(self)


def rank(shape: Shape, overhang_limit: float = 45.0, max_bridge: float = 10.0,
         samples: int = 3) -> list[Orientation]:
    results = []
    for name, rot in CANDIDATES.items():
        rx, ry, rz = rot
        s = shape.rotate(Axis.X, rx) if rx else shape
        s = s.rotate(Axis.Y, ry) if ry else s
        s = s.rotate(Axis.Z, rz) if rz else s
        bb = s.bounding_box()
        s = s.moved(Location((0, 0, -bb.min.Z)))   # sit on the bed
        rep = inspect(s, samples=samples, overhang_min_angle=overhang_limit)
        ov_area = sum(o.area for o in rep.overhangs if not o.flat and o.angle_from_vertical > overhang_limit)
        ceilings = [o for o in rep.overhangs if o.flat]
        ceil_area = sum(o.area for o in ceilings)
        bridge = max((o.span or 0 for o in ceilings), default=0.0)
        steep = max((o.angle_from_vertical for o in rep.overhangs if not o.flat), default=0.0)
        fp = rep.footprint_area
        h = rep.size[2]
        notes = []
        # score: lower is better
        score = 0.0
        score += ov_area * 1.0 + ceil_area * 1.5
        if bridge > max_bridge:
            score += (bridge - max_bridge) * 20
            notes.append(f"{bridge:.0f} mm bridge")
        if fp < 100:
            score += 400
            notes.append("tiny footprint")
        elif fp < 400:
            score += 100
        score += h * 2   # taller = slower
        if steep > overhang_limit + 15:
            notes.append(f"{steep:.0f}° overhang")
        if fp == 0:
            score += 2000
            notes.append("no flat base")
        results.append(Orientation(name, tuple(rot), round(h, 1), round(fp, 0),
                                   round(ov_area + ceil_area, 0), round(steep, 0), round(bridge, 1),
                                   round(score, 0), notes))
    results.sort(key=lambda o: o.score)
    return results


def summary(ranked: list[Orientation]) -> str:
    lines = ["orientation            height  footprint  overhang  steepest  bridge  score"]
    for o in ranked:
        n = f"  ({', '.join(o.notes)})" if o.notes else ""
        lines.append(f"{o.name:<22s} {o.height:6.1f}  {o.footprint_area:8.0f}  {o.overhang_area:8.0f}  "
                     f"{o.steepest:7.0f}°  {o.bridge_span:5.1f}  {o.score:5.0f}{n}")
    best = ranked[0]
    lines.append("")
    if best.name.startswith("as-designed"):
        lines.append("best: print as designed.")
    else:
        lines.append(f"best: {best.name} — rotate ({best.rotation[0]:g}, {best.rotation[1]:g}, {best.rotation[2]:g}) "
                     "in the slicer, or rotate in build() so exports are already oriented.")
    return "\n".join(lines)
