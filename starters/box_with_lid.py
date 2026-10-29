"""Box with a friction-fit lid.  Lid is printed beside the box (two bodies)."""
from forge import *


class Params(ParamSet):
    inner_x: mm = Param(60, min=10, max=200, step=1, doc="Inside length")
    inner_y: mm = Param(40, min=10, max=200, step=1, doc="Inside width")
    inner_z: mm = Param(25, min=5, max=150, step=1, doc="Inside height")
    wall:    mm = Param(1.6, min=0.8, max=6, step=0.4, doc="Wall thickness")
    floor:   mm = Param(1.6, min=0.8, max=6, step=0.4, doc="Floor / lid thickness")
    corner:  mm = Param(4, min=0, max=20, step=0.5, doc="Outside corner radius")
    lip:     mm = Param(4, min=2, max=12, step=0.5, doc="Lid lip height")
    lid_gap: mm = Param(0.2, min=0.0, max=0.6, step=0.05, doc="Clearance between lip and box (0.2 = snug)")
    with_lid: bool = Param(True, doc="Include the lid")


MANUFACTURING = FDM(nozzle=0.4, layer=0.2, material="PLA")


def _rounded(x, y, r, mode=Mode.ADD):
    r = max(0.0, min(r, min(x, y) / 2 - 0.05))
    if r <= 0:
        Rectangle(x, y, mode=mode)
    else:
        RectangleRounded(x, y, r, mode=mode)


def build(p: Params):
    ox, oy = p.inner_x + 2 * p.wall, p.inner_y + 2 * p.wall
    oz = p.inner_z + p.floor

    with BuildPart() as box:
        with BuildSketch():
            _rounded(ox, oy, p.corner)
        extrude(amount=oz)
        top = box.faces().sort_by(Axis.Z)[-1]
        offset(amount=-p.wall, openings=top)           # hollow with open top
        # (re-)set floor thickness: offset used `wall`; add a floor pad if floor != wall
        if p.floor > p.wall:
            with BuildSketch(Plane.XY.offset(p.wall)):
                _rounded(p.inner_x + 0.02, p.inner_y + 0.02, max(p.corner - p.wall, 0))
            extrude(amount=p.floor - p.wall)
    body = box.part

    if not p.with_lid:
        return body

    # Lid: a plate the size of the box outside, with a lip that drops inside the walls.
    lip_x = p.inner_x - 2 * p.lid_gap
    lip_y = p.inner_y - 2 * p.lid_gap
    with BuildPart() as lid:
        with BuildSketch():
            _rounded(ox, oy, p.corner)
        extrude(amount=p.floor)
        with BuildSketch(Plane.XY.offset(p.floor)):
            _rounded(lip_x, lip_y, max(p.corner - p.wall - p.lid_gap, 0))
            # hollow lip to save material (keep it ≥ 2 perimeters)
            inner_r = max(p.corner - 2 * p.wall - p.lid_gap, 0)
            if lip_x - 2 * p.wall > 4 and lip_y - 2 * p.wall > 4:
                _rounded(lip_x - 2 * p.wall, lip_y - 2 * p.wall, inner_r, mode=Mode.SUBTRACT)  # → ring
        extrude(amount=p.lip)
        # small chamfer on the lip so it finds the opening
        try:
            lip_top = lid.faces().sort_by(Axis.Z)[-1]
            chamfer(lip_top.outer_wire().edges(), length=min(0.6, p.lip / 3, p.wall / 3))
        except Exception:
            pass
    lid_part = lid.part.moved(Location((ox + 10, 0, 0)))

    return [body, lid_part]
