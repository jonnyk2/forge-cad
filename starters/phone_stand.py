"""Phone / tablet stand with a cable slot.  Prints flat on its base, no supports."""
import math

from forge import *


class Params(ParamSet):
    width:     mm  = Param(70, min=40, max=160, step=1, doc="Stand width")
    depth:     mm  = Param(60, min=40, max=120, step=1, doc="Base depth (front to back)")
    angle:     deg = Param(65, min=50, max=80, step=1, doc="Screen angle from horizontal")
    back_h:    mm  = Param(70, min=30, max=150, step=1, doc="Backrest height along the slope")
    thick:     mm  = Param(5, min=2.4, max=12, step=0.4, doc="Base and backrest thickness")
    lip_h:     mm  = Param(12, min=5, max=30, step=1, doc="Front lip height")
    device_t:  mm  = Param(11, min=6, max=25, step=0.5, doc="Device thickness incl. case")
    cable_slot: bool = Param(True, doc="Slot for a charging cable")
    cable_w:   mm  = Param(14, min=6, max=30, step=1, doc="Cable slot width")


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PLA")


def build(p: Params):
    a = math.radians(p.angle)
    t = p.thick
    # Side profile in the XZ plane (X = front→back, Z = up), extruded along Y.
    # Base plate, then a backrest leaning back at `angle`, a front lip, and a
    # cradle gap between lip and backrest for the device.
    cradle_x = t + 2 + p.device_t + 2         # where the backrest meets the base
    bx = p.back_h * math.cos(a)                # backrest run
    bz = p.back_h * math.sin(a)                # backrest rise
    # backrest as a parallelogram: bottom edge from cradle_x to cradle_x+t (at z=t)
    pts = [
        (0, 0), (p.depth, 0), (p.depth, t),
        (cradle_x + t + bx, t + bz), (cradle_x + bx, t + bz),
        (cradle_x, t), (t, t), (t, t + p.lip_h), (0, t + p.lip_h),
    ]
    with BuildPart() as s:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline(*pts, close=True)
            make_face()
        extrude(amount=p.width / 2, both=True)
        # gusset under the backrest so it isn't an overhang: fill the triangle between
        # backrest underside and base, out to the base's back edge
        with BuildSketch(Plane.XZ):
            with BuildLine():
                gx = min(p.depth, cradle_x + t + bx)
                gz = t + (gx - (cradle_x + t)) * math.tan(a)
                Polyline((cradle_x + t - 0.01, t - 0.01), (gx, t - 0.01), (gx, min(gz, t + bz)), close=True)
            make_face()
        extrude(amount=p.width / 2, both=True)
        if p.cable_slot:
            # slot through the base and lip, centred, from the front to the cradle
            with BuildSketch(Plane.XY.offset(-0.1)):
                with Locations((cradle_x / 2 + 2, 0)):
                    SlotCenterToCenter(cradle_x, p.cable_w)
            extrude(amount=t + p.lip_h + 0.2, mode=Mode.SUBTRACT)
        # round the vertical-ish side edges lightly
        try:
            fillet(s.edges().filter_by(Axis.Y), radius=min(1.5, t / 3))
        except Exception:
            pass
    part = s.part
    bb = part.bounding_box()
    return part.moved(Location((-bb.min.X, 0, -bb.min.Z)))
