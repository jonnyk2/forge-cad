"""Parameter declarations.

A part file declares its parameters as a ``ParamSet`` subclass::

    class Params(ParamSet):
        width: mm = Param(70, min=40, max=120, step=1, doc="Overall width")
        angle: deg = Param(65, min=45, max=80)
        hollow: bool = Param(True)
        style: str = Param("round", choices=["round", "square"])

The declared metadata is the *only* schema: the web UI renders controls from
it, the MCP server validates against it, and the CLI parses ``--width 80``
from it.  Nothing else to keep in sync.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Optional

# ---- unit tags: float/int subclasses so the UI can show units ----
class mm(float):
    """millimetres"""
class deg(float):
    """degrees"""
class count(int):
    """a whole number of things"""


class _Missing:
    pass


_MISSING = _Missing()


@dataclasses.dataclass
class Param:
    """Metadata for one parameter.  Used as the default value in a ParamSet."""

    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list] = None
    doc: str = ""
    unit: str = ""          # "mm", "deg", "" ; filled from the annotation if blank
    group: str = ""         # optional UI grouping
    advanced: bool = False  # hide behind "advanced" in the UI

    def kind(self, annotation) -> str:
        if self.choices is not None:
            return "choice"
        if isinstance(annotation, str):  # `from __future__ import annotations`
            annotation = {"mm": float, "deg": float, "float": float, "int": int,
                          "count": int, "bool": bool, "str": str}.get(annotation, None)
        is_t = lambda t: isinstance(annotation, type) and issubclass(annotation, t)
        if is_t(bool) or (annotation is None and isinstance(self.default, bool)):
            return "bool"
        if is_t(float):
            return "float"
        if is_t(int) or (annotation is None and isinstance(self.default, int)):
            return "int"
        if is_t(str) or (annotation is None and isinstance(self.default, str)):
            return "str"
        return "float"


class ParamSetMeta(type):
    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        specs: dict[str, dict] = {}
        for base in reversed(bases):
            specs.update(getattr(base, "__param_specs__", {}))
        ann = ns.get("__annotations__", {})
        for key, value in ns.items():
            if key.startswith("_"):
                continue
            if isinstance(value, Param):
                a = ann.get(key, type(value.default))
                unit = value.unit or _unit_name(a)
                specs[key] = {
                    "name": key,
                    "kind": value.kind(a),
                    "default": value.default,
                    "min": value.min,
                    "max": value.max,
                    "step": value.step,
                    "choices": value.choices,
                    "doc": value.doc,
                    "unit": unit,
                    "group": value.group,
                    "advanced": value.advanced,
                }
                setattr(cls, key, value.default)
        cls.__param_specs__ = specs
        return cls


def _unit_name(annotation) -> str:
    if isinstance(annotation, str):
        return annotation if annotation in ("mm", "deg") else ""
    if annotation is mm:
        return "mm"
    if annotation is deg:
        return "deg"
    return ""


class ParamSet(metaclass=ParamSetMeta):
    """Base class for a part's parameters.

    Instances are plain attribute bags validated against the declared specs.
    """

    __param_specs__: dict[str, dict] = {}

    def __init__(self, **overrides):
        for name, spec in self.__param_specs__.items():
            setattr(self, name, spec["default"])
        self.update(overrides)

    # ---- construction / mutation ------------------------------------------
    def update(self, values: Mapping[str, Any]) -> "ParamSet":
        errors = []
        for key, raw in values.items():
            if key not in self.__param_specs__:
                errors.append(f"unknown parameter {key!r}; known: {list(self.__param_specs__)}")
                continue
            try:
                setattr(self, key, self.coerce(key, raw))
            except ValueError as e:
                errors.append(str(e))
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def coerce(cls, key: str, raw: Any) -> Any:
        spec = cls.__param_specs__[key]
        kind = spec["kind"]
        if kind == "bool":
            if isinstance(raw, str):
                raw = raw.strip().lower() in ("1", "true", "yes", "on", "y")
            return bool(raw)
        if kind == "choice":
            if raw not in spec["choices"]:
                raise ValueError(f"{key} must be one of {spec['choices']}, got {raw!r}")
            return raw
        if kind == "str":
            return str(raw)
        if kind == "int":
            v = int(round(float(raw)))
        else:
            v = float(raw)
            if math.isnan(v) or math.isinf(v):
                raise ValueError(f"{key} must be finite")
        if spec["min"] is not None and v < spec["min"]:
            raise ValueError(f"{key}={v} below minimum {spec['min']}")
        if spec["max"] is not None and v > spec["max"]:
            raise ValueError(f"{key}={v} above maximum {spec['max']}")
        return v

    # ---- introspection ----------------------------------------------------
    @classmethod
    def specs(cls) -> list[dict]:
        return list(cls.__param_specs__.values())

    def values(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__param_specs__}

    def hash(self, length: int = 8) -> str:
        """Stable short hash of the parameter values; used in export filenames."""
        blob = json.dumps(self.values(), sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:length]

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.values().items())
        return f"{type(self).__name__}({inner})"

    # ---- CLI helper ---------------------------------------------------------
    @classmethod
    def from_cli(cls, args: Iterable[str]) -> "ParamSet":
        """Parse ``--name value`` or ``name=value`` pairs."""
        values: dict[str, str] = {}
        it = iter(args)
        for tok in it:
            if tok.startswith("--"):
                key = tok[2:]
                if "=" in key:
                    key, val = key.split("=", 1)
                else:
                    val = next(it, "true")
                values[key] = val
            elif "=" in tok:
                key, val = tok.split("=", 1)
                values[key] = val
            else:
                raise ValueError(f"cannot parse parameter argument {tok!r}")
        return cls(**values)


class EmptyParams(ParamSet):
    """Used for part files that declare no Params class."""
