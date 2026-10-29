"""Export to manufacturing and interchange formats.

File names carry the parameter hash so a printed object can be traced back
to the exact parameters that made it:  ``phone_stand-3fa9c1d2.3mf``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from build123d import (Axis, ExportSVG, LineType, Shape, Unit, export_gltf,
                       export_step, export_stl)

FORMATS = ("stl", "3mf", "step", "glb", "svg", "json")


def _name(built, fmt: str, out_dir: Path, tag: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"-{tag}" if tag else ""
    return out_dir / f"{built.part.name}-{built.params.hash()}{tag}.{fmt}"


def export(built, formats: Iterable[str] = ("stl", "3mf", "step"), out_dir: str | Path = "out",
           tolerance: float = 0.02, angular_tolerance: float = 0.1) -> dict[str, str]:
    """Export a Built part.  Returns {format: path}."""
    out_dir = Path(out_dir)
    shape = built.shape
    written: dict[str, str] = {}
    for fmt in formats:
        fmt = fmt.lower().lstrip(".")
        if fmt == "stl":
            p = _name(built, "stl", out_dir)
            export_stl(shape, str(p), tolerance=tolerance, angular_tolerance=angular_tolerance)
        elif fmt == "3mf":
            p = _name(built, "3mf", out_dir)
            _export_3mf(shape, p, tolerance, angular_tolerance, built.part.name)
        elif fmt in ("step", "stp"):
            p = _name(built, "step", out_dir)
            export_step(shape, str(p))
        elif fmt in ("glb", "gltf"):
            p = _name(built, "glb", out_dir)
            export_gltf(shape, str(p), binary=True, linear_deflection=tolerance,
                        angular_deflection=angular_tolerance)
        elif fmt == "svg":
            p = _name(built, "svg", out_dir)
            drawing(shape, p)
        elif fmt == "json":
            p = _name(built, "json", out_dir)
            p.write_text(json.dumps(built.to_dict(), indent=2, default=str))
        else:
            raise ValueError(f"unknown export format {fmt!r}; choose from {FORMATS}")
        written[fmt] = str(p)
    return written


def _export_3mf(shape: Shape, path: Path, tol: float, ang: float, name: str):
    try:
        from build123d import Mesher
        m = Mesher(unit=Unit.MM)
        m.add_shape(shape, linear_deflection=tol, angular_deflection=ang, part_number=name)
        m.add_meta_data("http://schemas.microsoft.com/3dmanufacturing/core/2015/02",
                        "Application", "forge", "string", True)
        m.write(str(path))
    except Exception as e:  # lib3mf missing or failed: fall back to STL with a note
        alt = path.with_suffix(".stl")
        export_stl(shape, str(alt), tolerance=tol, angular_tolerance=ang)
        raise RuntimeError(f"3MF export failed ({e}); wrote {alt} instead") from e


def drawing(shape: Shape, path: str | Path, view: str = "iso", hidden: bool = True,
            scale: float = 1.0) -> Path:
    """2-D line drawing (SVG) with hidden lines dashed."""
    from build123d import Vector
    look = {
        "iso": (1, -1, 1), "front": (0, -1, 0), "back": (0, 1, 0), "top": (0, 0, 1),
        "bottom": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0),
    }[view]
    vis, hid = shape.project_to_viewport(viewport_origin=Vector(look) * 1000)
    exp = ExportSVG(scale=scale, unit=Unit.MM)
    exp.add_layer("visible", line_weight=0.35)
    exp.add_layer("hidden", line_weight=0.2, line_type=LineType.ISO_DASH)
    exp.add_shape(vis, layer="visible")
    if hidden:
        exp.add_shape(hid, layer="hidden")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exp.write(str(path))
    return path


def mesh_arrays(shape: Shape, tolerance: float = 0.05, angular_tolerance: float = 0.2):
    """Triangles as flat lists, for the web viewer: (vertices[xyz...], indices[...])."""
    verts: list[float] = []
    idx: list[int] = []
    base = 0
    for face in shape.faces():
        try:
            vs, tris = face.tessellate(tolerance, angular_tolerance)
        except Exception:
            continue
        for v in vs:
            verts.extend((v.X, v.Y, v.Z))
        for t in tris:
            idx.extend((base + t[0], base + t[1], base + t[2]))
        base += len(vs)
    return verts, idx


def mesh_json(shape: Shape, **kw) -> dict:
    v, i = mesh_arrays(shape, **kw)
    bb = shape.bounding_box()
    return {"vertices": [round(x, 3) for x in v], "indices": i,
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def edges_json(shape: Shape, tolerance: float = 0.1) -> list[list[float]]:
    """Polylines for the B-rep edges (drawn over the mesh in the viewer)."""
    out = []
    for e in shape.edges():
        try:
            n = max(2, int(e.length / 2) + 1) if e.geom_type.name != "LINE" else 2
            pts = [e @ (k / (n - 1)) for k in range(n)]
            out.append([round(c, 3) for p in pts for c in (p.X, p.Y, p.Z)])
        except Exception:
            continue
    return out
