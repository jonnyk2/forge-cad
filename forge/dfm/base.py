"""Design-for-manufacturing core: processes, violations, rule registry."""
from __future__ import annotations

import dataclasses
from typing import Callable, Optional

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclasses.dataclass
class Violation:
    rule: str
    severity: str               # "error" | "warn" | "info"
    message: str
    location: Optional[tuple[float, float, float]] = None
    value: Optional[float] = None
    limit: Optional[float] = None
    fix: str = ""               # suggested fix, ideally in Params terms
    extra: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if self.location is not None:
            d["location"] = [round(c, 2) for c in self.location]
        return d

    def __str__(self) -> str:
        loc = ""
        if self.location is not None:
            x, y, z = self.location
            loc = f" @ ({x:.1f}, {y:.1f}, {z:.1f})"
        s = f"{self.severity.upper():5s} {self.rule:<20s} {self.message}{loc}"
        if self.fix:
            s += f"\n      Try: {self.fix}"
        return s


@dataclasses.dataclass
class Manufacturing:
    """Base class for a manufacturing process declaration."""

    name: str = "generic"
    material: str = ""

    def rules(self) -> list["Rule"]:
        return []

    def describe(self) -> str:
        return self.name


@dataclasses.dataclass
class FDM(Manufacturing):
    """Fused-deposition 3D printing."""

    name: str = "fdm"
    nozzle: float = 0.4          # mm
    layer: float = 0.2           # mm
    material: str = "PLA"
    supports: bool = False       # if True, overhang rules relax to info
    max_overhang: float = 45.0   # degrees from vertical before warning
    max_bridge: float = 10.0     # mm before warning
    bed: tuple[float, float, float] = (220.0, 220.0, 250.0)
    # how much a hole shrinks when printed in XY, by nominal diameter (mm)
    hole_shrink_small: float = 0.3   # Ø<=5
    hole_shrink_medium: float = 0.2  # Ø 5-10
    hole_shrink_large: float = 0.1   # Ø>10

    def hole_compensation(self, d: float) -> float:
        if d <= 5:
            return self.hole_shrink_small
        if d <= 10:
            return self.hole_shrink_medium
        return self.hole_shrink_large

    def rules(self):
        from . import fdm
        return fdm.RULES

    def describe(self) -> str:
        return f"FDM {self.nozzle}mm nozzle, {self.layer}mm layers, {self.material}"


@dataclasses.dataclass
class EndMill:
    diameter: float
    flute_length: float = 0.0
    stickout: float = 0.0

    def __post_init__(self):
        if not self.flute_length:
            self.flute_length = 3 * self.diameter
        if not self.stickout:
            self.stickout = self.flute_length + self.diameter


@dataclasses.dataclass
class CNC(Manufacturing):
    """Subtractive milling.  Phase 2; declared now so part files can target it."""

    name: str = "cnc"
    axes: int = 3
    material: str = "6061"
    tools: list = dataclasses.field(default_factory=lambda: [EndMill(6), EndMill(3)])
    min_wall: float = 1.0

    @property
    def smallest_tool(self) -> EndMill:
        return min(self.tools, key=lambda t: t.diameter)

    def rules(self):
        from . import cnc
        return cnc.RULES

    def describe(self) -> str:
        tools = ", ".join(f"Ø{t.diameter:g}" for t in self.tools)
        return f"CNC {self.axes}-axis, {self.material}, tools: {tools}"


# A rule takes (part_report, geometry, process) and yields violations.
Rule = Callable[["object", "object", Manufacturing], list]


def run_rules(report, shape, process: Manufacturing) -> list[Violation]:
    out: list[Violation] = []
    for rule in process.rules():
        try:
            out.extend(rule(report, shape, process) or [])
        except Exception as e:  # a broken rule must never hide the others
            out.append(Violation(
                rule=getattr(rule, "__name__", "rule"),
                severity="info",
                message=f"rule could not run: {type(e).__name__}: {e}",
            ))
    out.sort(key=lambda v: (SEVERITY_ORDER.get(v.severity, 9), v.rule))
    return out
