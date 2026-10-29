"""L-bracket with a gusset and slotted holes.  Prints on its back face."""
from forge import *


class Params(ParamSet):
    base:    mm = Param(50, min=15, max=200, step=1, doc="Base leg length")
    upright: mm = Param(40, min=15, max=200, step=1, doc="Upright leg length")
    width:   mm = Param(30, min=10, max=150, step=1, doc="Bracket width")
    thick:   mm = Param(4, min=1.6, max=15, step=0.4, doc="Leg thickness")
    gusset:  bool = Param(True, doc="Triangular stiffener")
    screw:   str = Param("M4", choices=["M3", "M4", "M5", "M6"])
    slots:   bool = Param(True, doc="Slotted holes for adjustment")
    corner_r: mm = Param(2, min=0, max=10, step=0.5)


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PETG")


def build(p: Params):
    t = p.thick
    with BuildPart() as b:
        # L profile in the XZ plane, extruded along Y → prints lying on its back (upright leg down)
        with BuildSketch(Plane.XZ) as s:
            with BuildLine():
                Polyline((0, 0), (p.base, 0), (p.base, t), (t, t), (t, p.upright), (0, p.upright), close=True)
            make_face()
        extrude(amount=p.width / 2, both=True)
        if p.gusset:
            g = min(p.base, p.upright) * 0.6
            with BuildSketch(Plane.XZ) as s2:
                with BuildLine():
                    Polyline((t - 0.01, t - 0.01), (t + g, t - 0.01), (t - 0.01, t + g), close=True)
                make_face()
            extrude(amount=t / 2, both=True)
        # holes: two in the base (through Z), two in the upright (through X)
        d = screw_diameter(p.screw)
        hole_len = d * 1.6
        with BuildSketch(Plane.XY.offset(t)):
            with Locations(((p.base + t) / 2 + 2, 0)):
                with GridLocations(0, p.width * 0.55, 1, 2):
                    if p.slots:
                        SlotCenterToCenter(hole_len, d)
                    else:
                        Circle(d / 2)
        extrude(amount=-t - 0.1, mode=Mode.SUBTRACT)
        with BuildSketch(Plane.YZ.offset(t)):
            with Locations((0, (p.upright + t) / 2 + 2)):
                with GridLocations(p.width * 0.55, 0, 2, 1):
                    if p.slots:
                        SlotCenterToCenter(hole_len, d, rotation=90)
                    else:
                        Circle(d / 2)
        extrude(amount=-t - 0.1, mode=Mode.SUBTRACT)
        if p.corner_r > 0:
            try:
                fillet(b.edges().filter_by(Axis.Y).group_by(Axis.X)[-1], radius=min(p.corner_r, t / 2 - 0.1))
            except Exception:
                pass
    # orient for printing: upright leg's outer face (x=0 plane) goes on the bed
    part = b.part.rotate(Axis.Y, -90)
    bb = part.bounding_box()
    return part.moved(Location((-bb.min.X, 0, -bb.min.Z)))
