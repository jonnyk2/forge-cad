"""Topology for the viewer: faces and edges with ids, metadata and tessellation,
so a click on a triangle resolves to a B-rep face and a click near a line to a
B-rep edge.  Also the *selector* resolver: given a face/edge id, find a stable
build123d expression that names it, so UI commands can write code.
"""
from __future__ import annotations

import math
from typing import Optional

from build123d import Axis, Edge, Face, GeomType, Shape, SortBy, Vector
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve


# --------------------------------------------------------------------------
# tessellation with ids
# --------------------------------------------------------------------------

def _r(v, n=3):
    return round(float(v), n)


def face_info(f: Face, i: int) -> dict:
    d = {"id": i, "type": f.geom_type.name.lower(), "area": _r(f.area, 2)}
    try:
        c = f.center()
        d["center"] = [_r(c.X), _r(c.Y), _r(c.Z)]
    except Exception:
        pass
    try:
        if f.geom_type == GeomType.PLANE:
            n = f.normal_at()
            d["normal"] = [_r(n.X), _r(n.Y), _r(n.Z)]
        elif f.geom_type in (GeomType.CYLINDER, GeomType.CONE, GeomType.SPHERE, GeomType.TORUS):
            ad = BRepAdaptor_Surface(f.wrapped)
            if f.geom_type == GeomType.CYLINDER:
                cyl = ad.Cylinder(); d["radius"] = _r(cyl.Radius())
                ax = cyl.Axis().Direction(); d["axis"] = [_r(ax.X()), _r(ax.Y()), _r(ax.Z())]
            elif f.geom_type == GeomType.SPHERE:
                d["radius"] = _r(ad.Sphere().Radius())
            elif f.geom_type == GeomType.CONE:
                d["half_angle"] = _r(math.degrees(ad.Cone().SemiAngle()), 1)
    except Exception:
        pass
    bb = f.bounding_box()
    d["bbox"] = [[_r(bb.min.X), _r(bb.min.Y), _r(bb.min.Z)], [_r(bb.max.X), _r(bb.max.Y), _r(bb.max.Z)]]
    return d


def edge_info(e: Edge, i: int) -> dict:
    d = {"id": i, "type": e.geom_type.name.lower(), "length": _r(e.length, 3)}
    try:
        c = e.center()
        d["center"] = [_r(c.X), _r(c.Y), _r(c.Z)]
        if e.geom_type == GeomType.CIRCLE:
            d["radius"] = _r(e.radius)
        if e.geom_type == GeomType.LINE:
            t = e % 0.5
            d["dir"] = [_r(t.X), _r(t.Y), _r(t.Z)]
    except Exception:
        pass
    return d


def viewer_payload(shape: Shape, tolerance: float = 0.05, angular: float = 0.2) -> dict:
    """Mesh + per-face triangle ranges + edge polylines, all with ids."""
    verts: list[float] = []
    idx: list[int] = []
    faces_meta: list[dict] = []
    base = 0
    solids = list(shape.solids()) or [shape]
    solid_of_face: dict[int, int] = {}
    # map faces to the solid they belong to (for the browser / body picking)
    face_list = list(shape.faces())
    for si, s in enumerate(solids):
        for f in s.faces():
            for fi, g in enumerate(face_list):
                if g.is_same(f):
                    solid_of_face[fi] = si
                    break
    for fi, f in enumerate(face_list):
        try:
            vs, tris = f.tessellate(tolerance, angular)
        except Exception:
            vs, tris = [], []
        start = len(idx) // 3
        for v in vs:
            verts.extend((_r(v.X), _r(v.Y), _r(v.Z)))
        for t in tris:
            idx.extend((base + t[0], base + t[1], base + t[2]))
        base += len(vs)
        m = face_info(f, fi)
        m["tri_start"] = start
        m["tri_count"] = len(tris)
        m["body"] = solid_of_face.get(fi, 0)
        faces_meta.append(m)
    edges_meta: list[dict] = []
    polylines: list[list[float]] = []
    for ei, e in enumerate(shape.edges()):
        try:
            n = 2 if e.geom_type == GeomType.LINE else max(3, int(e.length / 1.5) + 2)
            pts = [e @ (k / (n - 1)) for k in range(n)]
            polylines.append([_r(c) for p in pts for c in (p.X, p.Y, p.Z)])
        except Exception:
            polylines.append([])
        edges_meta.append(edge_info(e, ei))
    bb = shape.bounding_box()
    bodies = []
    for si, s in enumerate(solids):
        sb = s.bounding_box()
        bodies.append({"id": si, "label": getattr(s, "label", "") or f"Body{si + 1}", "volume": _r(s.volume, 1),
                       "faces": sum(1 for fi, b in solid_of_face.items() if b == si),
                       "bbox": [[_r(sb.min.X), _r(sb.min.Y), _r(sb.min.Z)], [_r(sb.max.X), _r(sb.max.Y), _r(sb.max.Z)]]})
    return {"vertices": verts, "indices": idx, "faces": faces_meta, "edges": edges_meta, "polylines": polylines,
            "bodies": bodies, "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


# --------------------------------------------------------------------------
# selector resolution
# --------------------------------------------------------------------------

_AXES = [("Axis.Z", None), ("Axis.X", None), ("Axis.Y", None)]  # names only; evaluated via eval()
_GEOMS = ["PLANE", "CYLINDER", "CONE", "SPHERE", "TORUS", "BSPLINE_SURFACE", "LINE", "CIRCLE", "ELLIPSE", "BSPLINE_CURVE"]


def _candidates(kind: str, geom: str) -> list[str]:
    """Expressions in order of preference (most readable / stable first).  `{v}` = part variable."""
    c = []
    for ax, _ in _AXES:
        c += [f"{{v}}.{kind}().sort_by({ax})[-1]", f"{{v}}.{kind}().sort_by({ax})[0]"]
    if kind == "faces":
        for ax, _ in _AXES:
            for k in (-1, 0, 1, -2, 2, -3, 3):
                c.append(f"{{v}}.faces().filter_by({ax}).sort_by({ax})[{k}]")
    size = "SortBy.AREA" if kind == "faces" else "SortBy.LENGTH"
    c += [f"{{v}}.{kind}().sort_by({size})[-1]", f"{{v}}.{kind}().sort_by({size})[0]"]
    if geom in _GEOMS:
        for ax, _ in _AXES:
            for k in (-1, 0, 1, -2, 2, -3, 3, -4, 4):
                c.append(f"{{v}}.{kind}().filter_by(GeomType.{geom}).sort_by({ax})[{k}]")
        c += [f"{{v}}.{kind}().filter_by(GeomType.{geom}).sort_by({size})[-1]",
              f"{{v}}.{kind}().filter_by(GeomType.{geom}).sort_by({size})[0]"]
    for ax, _ in _AXES:
        for k in (-1, 0, 1, -2, 2):
            for j in (0, -1, 1):
                c.append(f"{{v}}.{kind}().group_by({ax})[{k}][{j}]")
    return c


def resolve_selector(shape: Shape, kind: str, index: int, var: str = "part") -> dict:
    """Find an expression that selects exactly the face/edge with this index.

    Returns {"expr": str, "stable": bool}.  Falls back to an index selector
    (fragile: indices change when the model changes) when nothing nicer matches.
    """
    import build123d as b3d
    items = list(shape.faces() if kind == "faces" else shape.edges())
    target = items[index]
    geom = target.geom_type.name
    ns = {**vars(b3d), var: shape}
    for tmpl in _candidates(kind, geom):
        expr = tmpl.replace("{v}", var)
        try:
            got = eval(expr, ns)
        except Exception:
            continue
        if got is None or isinstance(got, (list, tuple)):
            continue
        try:
            if got.is_same(target):
                return {"expr": expr, "stable": True}
        except Exception:
            continue
    return {"expr": f"{var}.{kind}()[{index}]", "stable": False}


def selector_ok(shape: Shape, expr: str, var: str = "part") -> bool:
    import build123d as b3d
    try:
        got = eval(expr, {**vars(b3d), var: shape})
        return got is not None
    except Exception:
        return False
