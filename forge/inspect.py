"""Geometry measurement.  Turns a solid into numbers the AI (or a human) can
reason about: size, mass, walls, holes, overhangs, footprint.

Everything here is pure measurement; judgement lives in ``forge.dfm``.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

from build123d import Axis, Face, GeomType, Shape, Solid, Vector, Compound
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_IN

DENSITY = {  # g/cm³
    "PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21,
    "NYLON": 1.14, "PC": 1.20, "6061": 2.70, "STEEL": 7.85, "BRASS": 8.5,
    "DELRIN": 1.41, "HDPE": 0.95, "PLYWOOD": 0.6,
}


@dataclasses.dataclass
class Hole:
    diameter: float
    axis_dir: tuple[float, float, float]
    center: tuple[float, float, float]
    length: float
    through: Optional[bool] = None

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ThinSpot:
    thickness: float
    location: tuple[float, float, float]
    normal: tuple[float, float, float]

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Overhang:
    angle_from_vertical: float       # degrees; 0 = vertical wall, 90 = ceiling
    area: float
    location: tuple[float, float, float]
    z_min: float
    z_max: float
    flat: bool                        # True for a horizontal downward face
    span: Optional[float] = None      # for flat faces: shortest planar extent

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Report:
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    size: tuple[float, float, float]
    volume: float
    area: float
    center_of_mass: tuple[float, float, float]
    n_solids: int
    n_faces: int
    n_edges: int
    valid: bool
    footprint_area: float
    footprint_size: tuple[float, float]
    thin_spots: list[ThinSpot]
    holes: list[Hole]
    overhangs: list[Overhang]
    material: str = ""
    mass_g: Optional[float] = None
    warnings: list[str] = dataclasses.field(default_factory=list)

    # ---- convenience -------------------------------------------------------
    @property
    def thinnest(self) -> Optional[ThinSpot]:
        return min(self.thin_spots, key=lambda t: t.thickness) if self.thin_spots else None

    @property
    def smallest_hole(self) -> Optional[Hole]:
        return min(self.holes, key=lambda h: h.diameter) if self.holes else None

    @property
    def height(self) -> float:
        return self.size[2]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["thinnest"] = self.thinnest.to_dict() if self.thinnest else None
        d["smallest_hole"] = self.smallest_hole.to_dict() if self.smallest_hole else None
        return d

    def summary(self) -> str:
        sx, sy, sz = self.size
        lines = [
            f"size:            {sx:.1f} × {sy:.1f} × {sz:.1f} mm  (X × Y × Z)",
            f"volume:          {self.volume:,.0f} mm³" + (f"  (~{self.mass_g:.1f} g {self.material} solid)" if self.mass_g else ""),
            f"surface area:    {self.area:,.0f} mm²",
            f"bodies:          {self.n_solids}  ({'valid' if self.valid else 'INVALID geometry'})",
            f"faces / edges:   {self.n_faces} / {self.n_edges}",
            f"center of mass:  ({self.center_of_mass[0]:.1f}, {self.center_of_mass[1]:.1f}, {self.center_of_mass[2]:.1f})",
            f"footprint (Z-):  {self.footprint_size[0]:.1f} × {self.footprint_size[1]:.1f} mm, {self.footprint_area:,.0f} mm² contact",
        ]
        t = self.thinnest
        if t:
            x, y, z = t.location
            lines.append(f"thinnest wall:   {t.thickness:.2f} mm @ ({x:.1f}, {y:.1f}, {z:.1f})")
        if self.holes:
            ds = sorted({round(h.diameter, 2) for h in self.holes})
            lines.append(f"holes:           {len(self.holes)}  Ø " + ", ".join(f"{d:g}" for d in ds))
        if self.overhangs:
            worst = max(self.overhangs, key=lambda o: o.angle_from_vertical)
            lines.append(f"steepest overhang: {worst.angle_from_vertical:.0f}° from vertical, {worst.area:.0f} mm² @ z={worst.z_min:.1f}–{worst.z_max:.1f}")
        for w in self.warnings:
            lines.append(f"note:            {w}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _solids(shape: Shape) -> list[Solid]:
    if isinstance(shape, Solid):
        return [shape]
    return list(shape.solids())


def _is_valid(shape: Shape) -> bool:
    try:
        return BRepCheck_Analyzer(shape.wrapped).IsValid()
    except Exception:
        return False


def _face_samples(face: Face, n: int) -> list[tuple[Vector, Vector]]:
    """Return up to n*n (point, outward normal) samples on a face's interior."""
    out = []
    for i in range(n):
        u = (i + 0.5) / n
        for j in range(n):
            v = (j + 0.5) / n
            try:
                p = face.position_at(u, v)
                if not face.is_inside(p, tolerance=1e-3):
                    continue
                nrm = face.normal_at(p)
            except Exception:
                continue
            out.append((p, nrm))
    return out


class _RayCaster:
    """One intersector per shape: loading builds a spatial index, so reuse it
    for every ray instead of rebuilding per sample (that was a 100× slowdown
    on parts with hundreds of faces, e.g. gears)."""

    def __init__(self, shape: Shape):
        self.isec = IntCurvesFace_ShapeIntersector()
        self.isec.Load(shape.wrapped, 1e-6)

    def thickness(self, p: Vector, inward: Vector, max_dist: float) -> Optional[float]:
        line = gp_Lin(gp_Pnt(p.X, p.Y, p.Z), gp_Dir(inward.X, inward.Y, inward.Z))
        self.isec.PerformNearest(line, 1e-3, max_dist)
        if self.isec.IsDone() and self.isec.NbPnt() >= 1:
            w = self.isec.WParameter(1)
            if w > 1e-3:
                return float(w)
        return None


def _face_area(face: Face) -> float:
    try:
        return float(face.area)
    except Exception:
        return 0.0


def _point_inside(shape: Shape, p: Vector) -> bool:
    c = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(p.X, p.Y, p.Z), 1e-6)
    return c.State() == TopAbs_IN


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------

def inspect(shape: Shape, material: str = "", samples: int = 4,
            thin_limit: float = 6.0, overhang_min_angle: float = 30.0) -> Report:
    """Measure a shape.

    samples            grid density per face for wall/overhang sampling
    thin_limit         only report walls thinner than this (mm)
    overhang_min_angle only report downward faces steeper than this (deg from vertical)
    """
    warnings: list[str] = []
    solids = _solids(shape)
    bb = shape.bounding_box()
    bmin, bmax = bb.min, bb.max
    size = (bmax.X - bmin.X, bmax.Y - bmin.Y, bmax.Z - bmin.Z)

    volume = float(shape.volume)
    area = float(shape.area)
    com = shape.center()
    faces = list(shape.faces())
    edges = list(shape.edges())
    valid = _is_valid(shape)
    if len(solids) == 0:
        warnings.append("no solid bodies — did build() return a sketch or a shell?")
    if len(solids) > 1:
        warnings.append(f"{len(solids)} separate bodies; a printer will treat them as one file")

    # ---- footprint: downward-facing planar faces at z == zmin ----------------
    footprint_area = 0.0
    fx0, fy0, fx1, fy1 = math.inf, math.inf, -math.inf, -math.inf
    for f in faces:
        if f.geom_type != GeomType.PLANE:
            continue
        fb = f.bounding_box()
        if abs(fb.min.Z - bmin.Z) > 1e-3 or fb.size.Z > 1e-3:
            continue
        n = f.normal_at()
        if n.Z < -0.99:
            footprint_area += _face_area(f)
            fx0, fy0 = min(fx0, fb.min.X), min(fy0, fb.min.Y)
            fx1, fy1 = max(fx1, fb.max.X), max(fy1, fb.max.Y)
    footprint_size = (fx1 - fx0, fy1 - fy0) if footprint_area > 0 else (0.0, 0.0)
    if footprint_area == 0:
        warnings.append("no flat face on the Z-min plane: part is not resting flat on the bed")

    # ---- holes: concave cylindrical faces --------------------------------
    holes: list[Hole] = []
    for f in faces:
        if f.geom_type != GeomType.CYLINDER:
            continue
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            cyl = ad.Cylinder()
            r = cyl.Radius()
            ax = cyl.Axis()
            loc, d = ax.Location(), ax.Direction()
            axis_pt = Vector(loc.X(), loc.Y(), loc.Z())
            axis_dir = Vector(d.X(), d.Y(), d.Z())
            p = f.position_at(0.5, 0.5)
            n = f.normal_at(p)
            radial = (p - axis_pt) - axis_dir * (p - axis_pt).dot(axis_dir)
            if radial.length < 1e-9:
                continue
            concave = n.dot(radial) < 0   # normal points toward the axis → hole
            if not concave:
                continue
            fb = f.bounding_box()
            length = abs((fb.max - fb.min).dot(axis_dir)) if axis_dir.length else 0.0
            c = f.center()
            holes.append(Hole(
                diameter=round(2 * r, 3),
                axis_dir=(round(axis_dir.X, 3), round(axis_dir.Y, 3), round(axis_dir.Z, 3)),
                center=(round(c.X, 2), round(c.Y, 2), round(c.Z, 2)),
                length=round(length, 2),
            ))
        except Exception:
            continue
    # merge the two half-cylinders OCC often produces for one hole
    merged: list[Hole] = []
    for h in holes:
        dup = next((m for m in merged if abs(m.diameter - h.diameter) < 1e-3
                    and _dist(m.center, h.center) < h.diameter), None)
        if dup is None:
            merged.append(h)
    holes = merged

    # ---- wall thickness + overhangs by sampling --------------------------
    thin: list[ThinSpot] = []
    overhangs: list[Overhang] = []
    max_ray = max(size) + 1.0
    caster = _RayCaster(shape)
    # budget: on face-heavy parts drop to 1 sample per face so inspect stays fast
    per_face_cap = samples if len(faces) < 200 else (2 if len(faces) < 600 else 1)
    for f in faces:
        fa = _face_area(f)
        if fa < 0.25:         # skip slivers
            continue
        n_s = max(1, min(per_face_cap, int(math.sqrt(fa) / 3) + 1))
        pts = _face_samples(f, n_s)
        if not pts:
            continue
        # thickness: shortest inward ray over the samples
        best = None
        for p, nrm in pts:
            t = caster.thickness(p, -nrm, min(max_ray, thin_limit * 2))
            if t is not None and (best is None or t < best[0]):
                best = (t, p, nrm)
        if best and best[0] < thin_limit:
            t, p, nrm = best
            thin.append(ThinSpot(round(t, 3), (p.X, p.Y, p.Z), (nrm.X, nrm.Y, nrm.Z)))

        # overhang: average normal of downward-facing samples
        down = [(p, nrm) for p, nrm in pts if nrm.Z < -1e-3]
        if len(down) >= max(1, len(pts) // 2):
            nz = sum(nrm.Z for _, nrm in down) / len(down)
            ang = math.degrees(math.asin(max(-1.0, min(1.0, -nz))))
            fb = f.bounding_box()
            on_bed = abs(fb.min.Z - bmin.Z) < 1e-3 and fb.size.Z < 1e-3
            if on_bed:
                continue
            flat = f.geom_type == GeomType.PLANE and nz < -0.999
            span = None
            if flat:
                span = round(min(fb.size.X, fb.size.Y), 2)
            if ang >= overhang_min_angle:
                c = f.center()
                overhangs.append(Overhang(round(ang, 1), round(fa, 1), (c.X, c.Y, c.Z),
                                          round(fb.min.Z, 2), round(fb.max.Z, 2), flat, span))

    thin.sort(key=lambda t: t.thickness)
    overhangs.sort(key=lambda o: -o.angle_from_vertical)

    mass = None
    if material and material.upper() in DENSITY:
        mass = volume / 1000.0 * DENSITY[material.upper()]

    return Report(
        bbox_min=(bmin.X, bmin.Y, bmin.Z), bbox_max=(bmax.X, bmax.Y, bmax.Z), size=size,
        volume=volume, area=area, center_of_mass=(com.X, com.Y, com.Z),
        n_solids=len(solids), n_faces=len(faces), n_edges=len(edges), valid=valid,
        footprint_area=footprint_area, footprint_size=footprint_size,
        thin_spots=thin[:20], holes=holes, overhangs=overhangs[:30],
        material=material, mass_g=mass, warnings=warnings,
    )


def _dist(a, b) -> float:
    return math.dist(a, b)


# --------------------------------------------------------------------------
# targeted measurements (for the `measure` tool)
# --------------------------------------------------------------------------

def distance(a: Shape, b: Shape) -> float:
    """Minimum distance between two shapes/faces/edges."""
    return float(a.distance_to(b))


def face_angle(a: Face, b: Face) -> float:
    """Angle in degrees between two faces' normals."""
    na, nb = a.normal_at(), b.normal_at()
    c = max(-1.0, min(1.0, na.dot(nb) / (na.length * nb.length)))
    return math.degrees(math.acos(c))
