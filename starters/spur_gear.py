"""Involute spur gear with bore and optional hub.  Pitch diameter = module × teeth."""
import math

from forge import *


class Params(ParamSet):
    module:   mm  = Param(2.0, min=0.5, max=6, step=0.25, doc="Gear module (tooth size)")
    teeth:    count = Param(20, min=8, max=120, step=1, doc="Number of teeth")
    width:    mm  = Param(8, min=2, max=40, step=0.5, doc="Face width")
    pressure: deg = Param(20, min=14.5, max=25, step=0.5, doc="Pressure angle")
    bore:     mm  = Param(5, min=1, max=30, step=0.5, doc="Shaft diameter (nominal)")
    bore_fit: str = Param("sliding", choices=["press", "snug", "sliding", "loose"])
    hub_d:    mm  = Param(0, min=0, max=60, step=1, doc="Hub diameter (0 = none)")
    hub_h:    mm  = Param(6, min=0, max=30, step=0.5, doc="Hub height above face")
    set_screw: bool = Param(False, doc="M3 set-screw hole in the hub")
    backlash: mm  = Param(0.1, min=0, max=0.5, step=0.05, doc="Tooth thinning for printed clearance")


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PETG")


def _rot(pt, a):
    c, s = math.cos(a), math.sin(a)
    return (pt[0] * c - pt[1] * s, pt[0] * s + pt[1] * c)


def _flank(m, z, pa_deg, backlash, n=8):
    """Points of the +side involute flank of a tooth centred on +X, root → tip."""
    pa = math.radians(pa_deg)
    r_p = m * z / 2
    r_b = r_p * math.cos(pa)
    r_a = r_p + m
    r_f = r_p - 1.25 * m
    r0 = max(r_b, r_f)

    def inv(a):
        return math.tan(a) - a

    half_t = (math.pi / (2 * z)) - (backlash / 2) / r_p
    base_ang = half_t + inv(math.acos(r_b / r_p))
    pts = []
    for i in range(n + 1):
        r = r0 + (r_a - r0) * i / n
        phi = math.acos(min(1.0, r_b / r))
        ang = base_ang - inv(phi)
        pts.append((r * math.cos(ang), r * math.sin(ang)))
    return pts, r_f, r0, r_a


def gear_outline(m, z, pa_deg, backlash):
    """Emit one closed wire for the whole gear inside an active BuildLine."""
    flank, r_f, r0, r_a = _flank(m, z, pa_deg, backlash)
    pitch = 2 * math.pi / z
    for k in range(z):
        a = k * pitch
        up = [_rot(p, a) for p in flank]                    # +side flank, root→tip
        dn = [_rot((x, -y), a) for (x, y) in reversed(flank)]  # -side flank, tip→root
        # tooth, going counter-clockwise: -side root up to tip, across tip, +side tip down to root
        dn_r = list(reversed(dn))                           # -side, root→tip
        Spline(*dn_r)
        # tip arc from -side tip to +side tip
        tip_mid = _rot((r_a, 0), a)
        ThreePointArc(dn_r[-1], tip_mid, up[-1])
        Spline(*reversed(up))                               # +side, tip→root
        # root: radial step down to r_f (if dedendum below base circle) then arc to next tooth
        start = up[0]
        ang_s = math.atan2(start[1], start[0])
        nxt = _rot(dn_r[0], pitch)
        ang_e = math.atan2(nxt[1], nxt[0])
        if ang_e < ang_s:
            ang_e += 2 * math.pi
        if r_f < r0 - 1e-6:
            p1 = (r_f * math.cos(ang_s), r_f * math.sin(ang_s))
            p2 = (r_f * math.cos(ang_e), r_f * math.sin(ang_e))
            Line(start, p1)
            mid = ((ang_s + ang_e) / 2)
            ThreePointArc(p1, (r_f * math.cos(mid), r_f * math.sin(mid)), p2)
            Line(p2, nxt)
        else:
            mid = (ang_s + ang_e) / 2
            ThreePointArc(start, (r_f * math.cos(mid), r_f * math.sin(mid)), nxt)


def build(p: Params):
    z = int(p.teeth)
    with BuildPart() as g:
        with BuildSketch() as s:
            with BuildLine():
                gear_outline(p.module, z, p.pressure, p.backlash)
            make_face()
        extrude(amount=p.width)
        if p.hub_d > 0 and p.hub_h > 0:
            with Locations((0, 0, p.width)):
                Cylinder(p.hub_d / 2, p.hub_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
        top = g.faces().sort_by(Axis.Z)[-1]
        with Locations(top):
            pin_hole(p.bore, fit=p.bore_fit)
        if p.set_screw and p.hub_d > 0:
            with BuildSketch(Plane.XZ) as ss:
                with Locations((0, p.width + p.hub_h / 2)):
                    Circle(screw_diameter("M3", "tap") / 2)
            extrude(amount=p.hub_d, both=True, mode=Mode.SUBTRACT)
    return g.part


def pitch_diameter(p: Params) -> float:
    return p.module * p.teeth
