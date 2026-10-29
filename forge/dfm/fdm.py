"""FDM (filament 3D printing) manufacturability rules.

Each rule is ``rule(report, shape, process) -> list[Violation]``.  Add a rule
by writing a function and appending it to ``RULES``.
"""
from __future__ import annotations

import math

from .base import FDM, Violation


def _loc(t):
    return tuple(round(c, 2) for c in t)


def geometry_valid(report, shape, p: FDM):
    out = []
    if not report.valid:
        out.append(Violation("invalid_geometry", "error",
                             "OpenCascade reports the solid is not valid; exports may be broken",
                             fix="simplify the last boolean/fillet, or run shape.fix()"))
    if report.n_solids == 0:
        out.append(Violation("no_solid", "error", "no solid body was produced",
                             fix="make sure build() returns a Part/Solid, not a Sketch"))
    elif report.n_solids > 1:
        out.append(Violation("multiple_bodies", "warn",
                             f"{report.n_solids} disconnected bodies in one part",
                             fix="fuse them, or split into separate part files"))
    return out


def fits_bed(report, shape, p: FDM):
    bx, by, bz = p.bed
    sx, sy, sz = report.size
    out = []
    if sz > bz:
        out.append(Violation("too_tall", "error", f"part is {sz:.0f} mm tall; bed height is {bz:.0f} mm",
                             value=sz, limit=bz, fix="split the part or lay it down"))
    footprint_ok = (sx <= bx and sy <= by) or (sx <= by and sy <= bx)
    if not footprint_ok:
        diag = math.hypot(bx, by)
        if max(sx, sy) < diag * 0.95 and min(sx, sy) < 60:
            out.append(Violation("bed_fit_diagonal", "warn",
                                 f"{sx:.0f}×{sy:.0f} mm only fits the {bx:.0f}×{by:.0f} bed on the diagonal",
                                 fix="rotate 45° in the slicer, or shorten"))
        else:
            out.append(Violation("too_big", "error",
                                 f"{sx:.0f}×{sy:.0f} mm footprint exceeds the {bx:.0f}×{by:.0f} mm bed",
                                 fix="split the part into pieces with alignment pins"))
    return out


def wall_thickness(report, shape, p: FDM):
    out = []
    one_wall = p.nozzle * 2          # two perimeters minimum
    sturdy = p.nozzle * 4
    seen = 0
    for t in report.thin_spots:
        if t.thickness < one_wall:
            out.append(Violation("wall_too_thin", "error",
                                 f"wall is {t.thickness:.2f} mm; {p.nozzle} mm nozzle needs ≥ {one_wall:.1f} mm (2 perimeters)",
                                 location=_loc(t.location), value=t.thickness, limit=one_wall,
                                 fix=f"thicken to ≥ {sturdy:.1f} mm, or make it a multiple of {p.nozzle*2:.1f} mm so perimeters fill it exactly"))
            seen += 1
        elif t.thickness < sturdy:
            out.append(Violation("wall_thin", "warn",
                                 f"wall is {t.thickness:.2f} mm; fine for cosmetic walls, weak if load-bearing (≥ {sturdy:.1f} mm recommended)",
                                 location=_loc(t.location), value=t.thickness, limit=sturdy))
            seen += 1
        if seen >= 6:
            break
    return out


def overhangs(report, shape, p: FDM):
    out = []
    limit = p.max_overhang
    hard = min(90.0, limit + 15)
    sev_bump = "info" if p.supports else None
    n = 0
    for o in report.overhangs:
        if o.flat:
            continue  # handled by bridges()
        if o.angle_from_vertical > hard:
            sev = sev_bump or "error"
            msg = f"face slopes {o.angle_from_vertical:.0f}° from vertical ({o.area:.0f} mm², z={o.z_min:.1f}–{o.z_max:.1f}); will droop or fail without supports"
        elif o.angle_from_vertical > limit:
            sev = sev_bump or "warn"
            msg = f"face slopes {o.angle_from_vertical:.0f}° from vertical ({o.area:.0f} mm², z={o.z_min:.1f}–{o.z_max:.1f}); printable but rough underneath"
        else:
            continue
        out.append(Violation("overhang", sev, msg, location=_loc(o.location),
                             value=o.angle_from_vertical, limit=limit,
                             fix="add a 45° chamfer under it, reorient so this face is up or vertical, or enable supports"))
        n += 1
        if n >= 8:
            break
    return out


def bridges(report, shape, p: FDM):
    """Flat downward-facing faces above the bed: bridges or unsupported ceilings."""
    out = []
    n = 0
    for o in report.overhangs:
        if not o.flat or o.span is None:
            continue
        if o.span <= p.max_bridge:
            out.append(Violation("bridge", "info",
                                 f"{o.span:.1f} mm flat underside at z={o.z_min:.1f} ({o.area:.0f} mm²); bridges this short print fine",
                                 location=_loc(o.location), value=o.span, limit=p.max_bridge))
        elif o.span <= p.max_bridge * 2.5:
            out.append(Violation("bridge_long", "info" if p.supports else "warn",
                                 f"{o.span:.1f} mm flat underside at z={o.z_min:.1f} ({o.area:.0f} mm²); will sag unless both ends are supported and bridge settings are tuned",
                                 location=_loc(o.location), value=o.span, limit=p.max_bridge,
                                 fix="add a 45° chamfer or arch under it, reduce the span, or reorient"))
        else:
            out.append(Violation("unsupported_ceiling", "info" if p.supports else "error",
                                 f"{o.span:.1f} mm × {o.area/o.span:.1f} mm flat underside at z={o.z_min:.1f} has nothing beneath it",
                                 location=_loc(o.location), value=o.span, limit=p.max_bridge,
                                 fix="reorient so this face is on the bed or facing up, split the part, or enable supports"))
        n += 1
        if n >= 8:
            break
    return out


def hole_sizes(report, shape, p: FDM):
    out = []
    for h in report.holes:
        d = h.diameter
        vertical = abs(h.axis_dir[2]) > 0.99
        horizontal = abs(h.axis_dir[2]) < 0.01
        if d < p.nozzle * 3:
            out.append(Violation("hole_too_small", "warn",
                                 f"Ø{d:g} hole is under {p.nozzle*3:.1f} mm; it will likely close up",
                                 location=h.center, value=d, limit=p.nozzle * 3,
                                 fix="enlarge, or drill it after printing"))
        elif vertical and d <= 10:
            shrink = p.hole_compensation(d)
            out.append(Violation("hole_shrink", "info",
                                 f"Ø{d:g} vertical hole will print ~Ø{d - shrink:.1f}; forge.hole(fit=…) compensates automatically",
                                 location=h.center, value=d, limit=d - shrink))
        if horizontal and d > 6:
            out.append(Violation("horizontal_hole_sag", "warn",
                                 f"Ø{d:g} horizontal hole: the top of the circle is a {d:.0f} mm overhang and will sag",
                                 location=h.center, value=d, limit=6.0,
                                 fix="use forge.teardrop_hole() or a flattened top, or orient the axis vertically"))
    return out


def stability(report, shape, p: FDM):
    out = []
    fa = report.footprint_area
    sz = report.size[2]
    if fa <= 0:
        return out  # already noted in report.warnings → geometry rule
    fw = min(report.footprint_size) if report.footprint_size[0] > 0 else 0
    if fa < 100 and sz > 20:
        out.append(Violation("small_footprint", "warn",
                             f"only {fa:.0f} mm² touches the bed for a {sz:.0f} mm tall part; likely to detach or wobble",
                             value=fa, limit=100.0, fix="add a brim in the slicer, or widen the base / reorient"))
    elif fw > 0 and sz / fw > 5:
        out.append(Violation("tall_and_narrow", "warn",
                             f"height {sz:.0f} mm is {sz/fw:.1f}× the narrowest footprint dimension ({fw:.0f} mm)",
                             value=sz / fw, limit=5.0, fix="lay it down, add a brim, or print two halves"))
    return out


def print_estimate(report, shape, p: FDM):
    """Not a violation, just a useful number: rough time/filament at 20% infill."""
    vol_shell = min(report.volume, report.area * p.nozzle * 2 + report.area * p.layer * 6)
    vol_infill = max(0.0, report.volume - vol_shell) * 0.2
    vol = vol_shell + vol_infill
    grams = vol / 1000 * 1.24
    metres = vol / (math.pi * (1.75 / 2) ** 2) / 1000
    # ~ 10 mm³/s typical volumetric rate for a 0.4 nozzle at 0.2 layers
    minutes = vol / 10 / 60 * 1.3
    return [Violation("estimate", "info",
                      f"≈ {grams:.0f} g / {metres:.1f} m of 1.75 mm filament, ≈ {minutes/60:.1f} h at 20% infill (rough)",
                      extra={"grams": round(grams, 1), "metres": round(metres, 2), "minutes": round(minutes)})]


RULES = [geometry_valid, fits_bed, wall_thickness, overhangs, bridges, hole_sizes, stability, print_estimate]
