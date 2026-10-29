"""Standard dimensions a part designer reaches for constantly.

All values in millimetres.  Sources: ISO 273 (clearance holes), ISO 4032
(hex nuts), common heat-set insert catalogue values, standard bearing numbers.
"""
from __future__ import annotations

# nominal: (close clearance, normal clearance, loose clearance, tap drill, thread pitch)
METRIC_SCREWS = {
    "M2":   dict(close=2.2,  normal=2.4,  loose=2.6,  tap=1.6,  pitch=0.40, head_d=3.8,  head_h=2.0,  nut_af=4.0,  nut_h=1.6),
    "M2.5": dict(close=2.7,  normal=2.9,  loose=3.1,  tap=2.05, pitch=0.45, head_d=4.5,  head_h=2.5,  nut_af=5.0,  nut_h=2.0),
    "M3":   dict(close=3.2,  normal=3.4,  loose=3.6,  tap=2.5,  pitch=0.50, head_d=5.5,  head_h=3.0,  nut_af=5.5,  nut_h=2.4),
    "M4":   dict(close=4.3,  normal=4.5,  loose=4.8,  tap=3.3,  pitch=0.70, head_d=7.0,  head_h=4.0,  nut_af=7.0,  nut_h=3.2),
    "M5":   dict(close=5.3,  normal=5.5,  loose=5.8,  tap=4.2,  pitch=0.80, head_d=8.5,  head_h=5.0,  nut_af=8.0,  nut_h=4.7),
    "M6":   dict(close=6.4,  normal=6.6,  loose=7.0,  tap=5.0,  pitch=1.00, head_d=10.0, head_h=6.0,  nut_af=10.0, nut_h=5.2),
    "M8":   dict(close=8.4,  normal=9.0,  loose=10.0, tap=6.8,  pitch=1.25, head_d=13.0, head_h=8.0,  nut_af=13.0, nut_h=6.8),
    "M10":  dict(close=10.5, normal=11.0, loose=12.0, tap=8.5,  pitch=1.50, head_d=16.0, head_h=10.0, nut_af=16.0, nut_h=8.4),
    "M12":  dict(close=13.0, normal=13.5, loose=14.5, tap=10.2, pitch=1.75, head_d=18.0, head_h=12.0, nut_af=18.0, nut_h=10.8),
}
# head_d / head_h are for ISO 4762 socket head cap screws (the usual choice for printed parts)

# Heat-set inserts (brass, for plastics): hole diameter and minimum boss OD / depth
HEATSET_INSERTS = {
    "M2":   dict(hole=3.2, depth=4.0, boss_od=5.6),
    "M2.5": dict(hole=3.6, depth=5.0, boss_od=6.4),
    "M3":   dict(hole=4.0, depth=5.7, boss_od=7.0),
    "M4":   dict(hole=5.6, depth=8.1, boss_od=9.0),
    "M5":   dict(hole=6.4, depth=9.5, boss_od=10.5),
    "M6":   dict(hole=8.0, depth=12.7, boss_od=12.5),
    "M8":   dict(hole=9.6, depth=12.7, boss_od=15.0),
}

# bearing number: (bore, outer diameter, width)
BEARINGS = {
    "MR63": (3, 6, 2.5), "MR83": (3, 8, 3), "MR93": (3, 9, 4), "MR105": (5, 10, 4),
    "MR115": (5, 11, 4), "MR128": (8, 12, 3.5), "623": (3, 10, 4), "624": (4, 13, 5),
    "625": (5, 16, 5), "626": (6, 19, 6), "627": (7, 22, 7), "608": (8, 22, 7),
    "609": (9, 24, 7), "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9),
    "6003": (17, 35, 10), "6004": (20, 42, 12), "6200": (10, 30, 9), "6201": (12, 32, 10),
    "6202": (15, 35, 11), "6203": (17, 40, 12), "6204": (20, 47, 14), "6805": (25, 37, 7),
    "6806": (30, 42, 7), "6900": (10, 22, 6), "6901": (12, 24, 6), "6902": (15, 28, 7),
    "688": (8, 16, 5), "685": (5, 11, 5), "F623": (3, 10, 4), "F608": (8, 22, 7),
}

# Common disc magnets: (diameter, thickness)
MAGNETS = {
    "3x2": (3, 2), "4x2": (4, 2), "5x2": (5, 2), "6x2": (6, 2), "6x3": (6, 3),
    "8x2": (8, 2), "8x3": (8, 3), "10x2": (10, 2), "10x3": (10, 3), "12x3": (12, 3),
    "15x3": (15, 3), "20x3": (20, 3),
}

# Fit allowances for printed parts (added to the *hole*, mating pin at nominal).
# These are on top of FDM hole-shrink compensation.
FDM_FITS = {
    "press":   -0.10,   # needs force; permanent
    "snug":     0.05,   # pushes in by hand, stays put
    "sliding":  0.20,   # moves freely, little slop (shafts, lids)
    "loose":    0.40,   # rattles; for bolts through, hinge pins
    "magnet":   0.10,   # press-fit a magnet without cracking the pocket
    "bearing":  0.00,   # bearings seat with a light press at nominal in PLA
}

# Typical wall/feature guidance for FDM at nozzle n and layer l
def fdm_guidance(nozzle: float = 0.4, layer: float = 0.2) -> dict:
    return {
        "min_wall": round(nozzle * 2, 2),
        "sturdy_wall": round(nozzle * 4, 2),
        "min_pin": round(nozzle * 4, 2),
        "min_text_depth": round(layer * 2, 2),
        "min_text_stroke": round(nozzle * 1.5, 2),
        "max_bridge": 10.0,
        "max_overhang_deg": 45,
        "living_hinge": round(layer * 3, 2),
        "chamfer_instead_of_fillet_on_bottom": 0.5,
        "elephant_foot_chamfer": 0.4,
    }


def screw(size: str) -> dict:
    try:
        return METRIC_SCREWS[size.upper()]
    except KeyError:
        raise KeyError(f"unknown screw size {size!r}; known: {list(METRIC_SCREWS)}")


def heatset(size: str) -> dict:
    try:
        return HEATSET_INSERTS[size.upper()]
    except KeyError:
        raise KeyError(f"unknown insert size {size!r}; known: {list(HEATSET_INSERTS)}")


def bearing(number: str) -> dict:
    try:
        b, od, w = BEARINGS[number.upper()]
    except KeyError:
        raise KeyError(f"unknown bearing {number!r}; known: {list(BEARINGS)}")
    return dict(bore=b, od=od, width=w)


def magnet(spec: str) -> dict:
    try:
        d, t = MAGNETS[spec.lower()]
    except KeyError:
        raise KeyError(f"unknown magnet {spec!r}; known: {list(MAGNETS)}")
    return dict(diameter=d, thickness=t)
