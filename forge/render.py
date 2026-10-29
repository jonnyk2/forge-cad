"""Renders the AI can read: PNG views with shading, B-rep edges, violation
markers, and section cuts.  Uses matplotlib so there is no GPU/VTK dependency.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402

from build123d import Axis, Box, Location, Plane, Shape, Vector  # noqa: E402

from .export import edges_json, mesh_arrays  # noqa: E402

VIEWS = {
    "iso":    dict(elev=28, azim=-55),
    "iso2":   dict(elev=28, azim=125),
    "front":  dict(elev=0, azim=-90),
    "back":   dict(elev=0, azim=90),
    "top":    dict(elev=90, azim=-90),
    "bottom": dict(elev=-90, azim=-90),
    "right":  dict(elev=0, azim=0),
    "left":   dict(elev=0, azim=180),
    "under":  dict(elev=-35, azim=-55),   # look up at overhangs
}

_LIGHT = np.array([0.4, -0.6, 0.7])
_LIGHT /= np.linalg.norm(_LIGHT)


def _tri_data(shape: Shape, tol=0.08, ang=0.3):
    v, i = mesh_arrays(shape, tol, ang)
    V = np.asarray(v, dtype=float).reshape(-1, 3)
    I = np.asarray(i, dtype=int).reshape(-1, 3)
    tris = V[I]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    return V, tris, n


def _draw(ax, shape: Shape, view: dict, markers=None, color=(0.78, 0.80, 0.86),
          highlight_down: bool = False, overhang_limit: float = 45.0):
    V, tris, n = _tri_data(shape)
    shade = 0.45 + 0.55 * np.clip(n @ _LIGHT, 0, 1)
    base = np.array(color)
    cols = np.clip(shade[:, None] * base[None, :], 0, 1)
    if highlight_down:
        # tint faces that overhang beyond the limit
        ang = np.degrees(np.arcsin(np.clip(-n[:, 2], 0, 1)))
        bad = (n[:, 2] < -1e-3) & (ang > overhang_limit) & (tris[:, :, 2].min(axis=1) > V[:, 2].min() + 1e-3)
        cols[bad] = cols[bad] * 0.3 + np.array([0.95, 0.35, 0.25]) * 0.7
    rgba = np.concatenate([cols, np.ones((len(cols), 1))], axis=1)
    pc = Poly3DCollection(tris, facecolors=rgba, edgecolors="none", linewidths=0)
    ax.add_collection3d(pc)

    segs = []
    for poly in edges_json(shape, 0.1):
        pts = np.asarray(poly).reshape(-1, 3)
        segs.extend(zip(pts[:-1], pts[1:]))
    if segs:
        ax.add_collection3d(Line3DCollection(segs, colors=(0.12, 0.12, 0.16, 0.9), linewidths=0.6))

    if markers:
        for m in markers:
            x, y, z = m["location"]
            c = {"error": "#d62728", "warn": "#ff9f1c", "info": "#3b82f6"}.get(m.get("severity"), "#d62728")
            ax.scatter([x], [y], [z], s=60, c=c, depthshade=False, edgecolors="black", linewidths=0.6, zorder=10)
            if m.get("label"):
                ax.text(x, y, z, "  " + m["label"], fontsize=6, color=c)

    lo, hi = V.min(axis=0), V.max(axis=0)
    c = (lo + hi) / 2
    r = max(hi - lo) / 2 * 1.15
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=view["elev"], azim=view["azim"])
    ax.set_axis_off()
    try:
        ax.set_proj_type("ortho")
    except Exception:
        pass


def render(shape: Shape, path: str | Path, views: Iterable[str] = ("iso", "front", "top", "right"),
           markers: Optional[list[dict]] = None, size: int = 900, title: str = "",
           highlight_overhangs: bool = False, overhang_limit: float = 45.0) -> Path:
    """Render one PNG containing the requested views in a grid."""
    views = list(views)
    cols = 2 if len(views) > 1 else 1
    rows = math.ceil(len(views) / cols)
    fig = plt.figure(figsize=(size / 100 * cols / 2 * 1.0 + 0.5, size / 100 * rows / 2 * 1.0 + 0.6), dpi=100)
    for k, name in enumerate(views):
        ax = fig.add_subplot(rows, cols, k + 1, projection="3d")
        _draw(ax, shape, VIEWS[name], markers if name in ("iso", "iso2", "under") else None,
              highlight_down=highlight_overhangs, overhang_limit=overhang_limit)
        ax.set_title(name, fontsize=9, pad=2)
    bb = shape.bounding_box()
    sz = bb.size
    sup = title or f"{sz.X:.1f} × {sz.Y:.1f} × {sz.Z:.1f} mm"
    fig.suptitle(sup, fontsize=10)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def section(shape: Shape, path: str | Path, plane: str = "XZ", offset: float = 0.0, size: int = 700) -> Path:
    """Cut the part with a plane and render the remaining half from the cut side.

    plane: "XZ" (cut at Y=offset, look from -Y), "YZ" (cut at X=offset), "XY" (cut at Z=offset)
    """
    bb = shape.bounding_box()
    big = max(bb.size) * 3
    c = bb.center()
    if plane == "XZ":
        cutter = Box(big, big, big).located(Location((c.X, offset + big / 2, c.Z)))
        view = VIEWS["front"]
    elif plane == "YZ":
        cutter = Box(big, big, big).located(Location((offset + big / 2, c.Y, c.Z)))
        view = VIEWS["left"]
    else:
        cutter = Box(big, big, big).located(Location((c.X, c.Y, offset + big / 2)))
        view = VIEWS["bottom"]
    half = shape.cut(cutter)
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    _draw(ax, half, view, color=(0.85, 0.72, 0.62))
    ax.set_title(f"section {plane} @ {offset:g}", fontsize=9)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def markers_from_violations(violations) -> list[dict]:
    out = []
    for v in violations:
        if v.location is None:
            continue
        out.append({"location": v.location, "severity": v.severity, "label": v.rule})
    return out
