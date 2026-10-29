"""Blank part: a plate with two screw holes.  Replace everything in build()."""
from forge import *


class Params(ParamSet):
    length: mm = Param(60, min=10, max=250, step=1, doc="Length (X)")
    width:  mm = Param(40, min=10, max=250, step=1, doc="Width (Y)")
    thick:  mm = Param(4, min=1.2, max=30, step=0.4, doc="Thickness (Z)")
    corner: mm = Param(3, min=0, max=20, step=0.5, doc="Corner radius")
    screw:  str = Param("M3", choices=["M2", "M2.5", "M3", "M4", "M5", "M6"], doc="Hole size")


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PLA")


def build(p: Params):
    with BuildPart() as part:
        with BuildSketch():
            if p.corner > 0:
                RectangleRounded(p.length, p.width, min(p.corner, min(p.length, p.width) / 2 - 0.1))
            else:
                Rectangle(p.length, p.width)
        extrude(amount=p.thick)
        top = part.faces().sort_by(Axis.Z)[-1]
        with Locations(top):
            with GridLocations(p.length - 12, 0, 2, 1):
                screw_hole(p.screw)
    return part.part
