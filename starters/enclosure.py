"""Electronics enclosure: base with heat-set bosses, screw-down lid, port cutouts.  Two bodies."""
from forge import *


class Params(ParamSet):
    pcb_x:   mm = Param(65, min=20, max=250, step=1, doc="PCB length")
    pcb_y:   mm = Param(45, min=20, max=250, step=1, doc="PCB width")
    clear:   mm = Param(2.0, min=0.5, max=10, step=0.5, doc="Clearance around PCB")
    inner_z: mm = Param(22, min=8, max=120, step=1, doc="Inside height")
    wall:    mm = Param(2.0, min=1.2, max=5, step=0.4)
    floor:   mm = Param(2.0, min=1.2, max=5, step=0.4)
    corner:  mm = Param(4, min=1, max=15, step=0.5)
    insert:  str = Param("M3", choices=["M2", "M2.5", "M3", "M4"], doc="Heat-set insert size")
    boss_h:  mm = Param(6, min=4, max=20, step=0.5, doc="Standoff height under the PCB")
    lid_t:   mm = Param(2.0, min=1.2, max=5, step=0.4)
    port:    bool = Param(True, doc="USB-C sized cutout in one wall")
    port_w:  mm = Param(10, min=4, max=40, step=0.5)
    port_h:  mm = Param(4, min=2, max=30, step=0.5)
    vents:   bool = Param(True, doc="Vent slots in the lid")


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PETG")


def build(p: Params):
    ix, iy = p.pcb_x + 2 * p.clear, p.pcb_y + 2 * p.clear
    ox, oy = ix + 2 * p.wall, iy + 2 * p.wall
    oz = p.inner_z + p.floor
    ins = heatset(p.insert)
    boss_od = ins["boss_od"]
    # boss centres: overlap the walls by 1 mm so the boss fuses into the corner
    # (a gap between boss and wall would be an unprintable sliver)
    bx, by = ix / 2 - boss_od / 2 + 1.0, iy / 2 - boss_od / 2 + 1.0

    with BuildPart() as base:
        with BuildSketch():
            RectangleRounded(ox, oy, p.corner)
        extrude(amount=oz)
        top = base.faces().sort_by(Axis.Z)[-1]
        offset(amount=-p.wall, openings=top)
        # floor pad to reach requested floor thickness
        if p.floor > p.wall:
            with BuildSketch(Plane.XY.offset(p.wall)):
                RectangleRounded(ix + 0.02, iy + 0.02, max(p.corner - p.wall, 0.1))
            extrude(amount=p.floor - p.wall)
        # PCB standoffs with insert holes (tall enough for the lid screws to also use them? no:
        # lid screws go into the top of taller corner bosses)
        with BuildSketch(Plane.XY.offset(p.floor)):
            with GridLocations(2 * bx, 2 * by, 2, 2):
                Circle(boss_od / 2)
        extrude(amount=p.inner_z)                      # full-height corner bosses
        with Locations(Plane.XY.offset(oz)):
            with GridLocations(2 * bx, 2 * by, 2, 2):
                screw_hole(p.insert, kind="heatset", depth=ins["depth"] + 1)
        # PCB standoffs (shorter, inboard) for M2.5 self-tappers
        sx, sy = p.pcb_x / 2 - 4, p.pcb_y / 2 - 4
        with BuildSketch(Plane.XY.offset(p.floor)):
            with GridLocations(2 * sx, 2 * sy, 2, 2):
                Circle(3.0)
        extrude(amount=p.boss_h)
        with Locations(Plane.XY.offset(p.floor + p.boss_h)):
            with GridLocations(2 * sx, 2 * sy, 2, 2):
                screw_hole("M2.5", kind="tap", depth=p.boss_h - 1)
        if p.port:
            # cutout in the +X wall, bottom aligned with the top of the standoffs
            with BuildSketch(Plane.YZ.offset(ox / 2 - p.wall - 0.1)):
                with Locations((0, p.floor + p.boss_h + 1.6 + p.port_h / 2)):
                    RectangleRounded(p.port_w, p.port_h, min(1.0, p.port_h / 2 - 0.1))
            extrude(amount=p.wall + 0.2, mode=Mode.SUBTRACT)
        try:
            chamfer(base.faces().sort_by(Axis.Z)[0].outer_wire().edges(), length=0.4)
        except Exception:
            pass
    body = base.part

    with BuildPart() as lid:
        with BuildSketch():
            RectangleRounded(ox, oy, p.corner)
        extrude(amount=p.lid_t)
        # locating lip that drops inside the walls
        with BuildSketch(Plane.XY.offset(p.lid_t)):
            RectangleRounded(ix - 0.4, iy - 0.4, max(p.corner - p.wall - 0.2, 0.1))
            RectangleRounded(ix - 0.4 - 2 * p.wall, iy - 0.4 - 2 * p.wall, max(p.corner - 2 * p.wall, 0.1), mode=Mode.SUBTRACT)
            # clear the corner bosses: a square that extends past the lip's outer edge
            clear = 2 * (ix / 2 - bx + 1.0)
            with GridLocations(2 * bx, 2 * by, 2, 2):
                Rectangle(clear, clear, mode=Mode.SUBTRACT)
        extrude(amount=2.0)
        with Locations(lid.faces().sort_by(Axis.Z)[0]):
            with GridLocations(2 * bx, 2 * by, 2, 2):
                screw_hole(p.insert, countersink=True)
        if p.vents and ix > 30:
            with BuildSketch(Plane.XY.offset(-0.1)):
                n = int(ix // 6)
                with GridLocations(6, 0, max(2, n - 2), 1):
                    SlotCenterToCenter(iy * 0.5, 1.6, rotation=90)
            extrude(amount=p.lid_t + 0.2, mode=Mode.SUBTRACT)
    lid_part = lid.part.moved(Location((ox + 10, 0, 0)))
    return [body, lid_part]
