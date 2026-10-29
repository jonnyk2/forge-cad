"""Loading and building part files.

A part file is a Python module that defines:

    class Params(ParamSet): ...            # optional
    MANUFACTURING = FDM(...)                # optional, default FDM()
    def build(p: Params) -> Part|Solid      # required

``load_part`` imports it in isolation; ``build_part`` runs it with a given
parameter set and returns a ``Built`` bundle: shape + report + violations.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import io
import sys
import time
import traceback
import types
from pathlib import Path
from typing import Any, Optional

from build123d import Compound, Part as B3dPart, Shape, Solid

from . import features
from .dfm.base import FDM, Manufacturing, Violation, run_rules
from .inspect import Report, inspect
from .params import EmptyParams, ParamSet


class PartError(Exception):
    """A part file failed to load or build.  `.detail` holds a trimmed
    traceback pointing at the part file's own lines."""

    def __init__(self, message: str, detail: str = "", line: Optional[int] = None):
        super().__init__(message)
        self.detail = detail
        self.line = line


@dataclasses.dataclass
class PartModule:
    path: Path
    module: types.ModuleType
    params_cls: type[ParamSet]
    process: Manufacturing
    doc: str

    @property
    def name(self) -> str:
        return self.path.stem

    def schema(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "doc": self.doc,
            "process": self.process.describe(),
            "params": self.params_cls.specs(),
        }


@dataclasses.dataclass
class Built:
    part: PartModule
    params: ParamSet
    shape: Shape
    report: Report
    violations: list[Violation]
    build_seconds: float
    stdout: str = ""

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        head = f"{self.part.name}  [{self.part.process.describe()}]  built in {self.build_seconds:.2f}s"
        params = "params: " + ", ".join(f"{k}={v}" for k, v in self.params.values().items())
        body = self.report.summary()
        if self.violations:
            n_err = len(self.errors)
            n_warn = sum(1 for v in self.violations if v.severity == "warn")
            checks = [f"checks: {n_err} error(s), {n_warn} warning(s)"]
            checks += [str(v) for v in self.violations]
        else:
            checks = ["checks: clean"]
        out = [head, params, "", body, ""] + checks
        if self.stdout.strip():
            out += ["", "--- part printed ---", self.stdout.rstrip()]
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "part": self.part.schema(),
            "params": self.params.values(),
            "param_hash": self.params.hash(),
            "ok": self.ok,
            "build_seconds": round(self.build_seconds, 3),
            "report": self.report.to_dict(),
            "violations": [v.to_dict() for v in self.violations],
            "stdout": self.stdout,
        }


# --------------------------------------------------------------------------

def load_part(path: str | Path) -> PartModule:
    path = Path(path).resolve()
    if not path.exists():
        raise PartError(f"part file not found: {path}")
    mod_name = f"forge_part_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    # make sibling imports work (shared helpers in the same project folder)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise PartError(f"error importing {path.name}: {type(e).__name__}: {e}",
                        detail=_trim_tb(path), line=_err_line(path)) from e

    build = getattr(module, "build", None)
    if not callable(build):
        raise PartError(f"{path.name} must define a function build(params)")
    params_cls = getattr(module, "Params", EmptyParams)
    if not (isinstance(params_cls, type) and issubclass(params_cls, ParamSet)):
        raise PartError(f"{path.name}: Params must subclass forge.ParamSet")
    process = getattr(module, "MANUFACTURING", None) or FDM()
    if not isinstance(process, Manufacturing):
        raise PartError(f"{path.name}: MANUFACTURING must be FDM(...) or CNC(...)")
    doc = (module.__doc__ or params_cls.__doc__ or "").strip()
    return PartModule(path, module, params_cls, process, doc)


def build_part(part: PartModule, params: Optional[ParamSet | dict] = None,
               check: bool = True, inspect_samples: int = 4) -> Built:
    if params is None:
        params = part.params_cls()
    elif isinstance(params, dict):
        params = part.params_cls(**params)
    features.set_process(part.process)

    buf = io.StringIO()
    old_stdout = sys.stdout
    t0 = time.perf_counter()
    try:
        sys.stdout = buf
        result = part.module.build(params)
    except Exception as e:
        raise PartError(f"build() failed: {type(e).__name__}: {e}",
                        detail=_trim_tb(part.path), line=_err_line(part.path)) from e
    finally:
        sys.stdout = old_stdout
    dt = time.perf_counter() - t0

    shape = _to_shape(result, part.path.name)
    report = inspect(shape, material=part.process.material, samples=inspect_samples)
    violations = run_rules(report, shape, part.process) if check else []
    return Built(part, params, shape, report, violations, dt, buf.getvalue())


def _to_shape(result: Any, name: str) -> Shape:
    # Accept Part, Solid, Compound, a BuildPart builder, or a list of solids
    if hasattr(result, "part") and not isinstance(result, Shape):
        result = result.part
    if isinstance(result, (list, tuple)):
        result = Compound(children=[_to_shape(r, name) for r in result])
    if not isinstance(result, Shape):
        raise PartError(f"{name}: build() returned {type(result).__name__}, expected a Part/Solid "
                        "(return builder.part from a BuildPart block)")
    if isinstance(result, Compound) and len(result.solids()) == 1 and not isinstance(result, Solid):
        return result  # keep as compound; inspect handles it
    return result


def _trim_tb(path: Path) -> str:
    """Only the traceback frames that are inside the part file."""
    tb = traceback.extract_tb(sys.exc_info()[2])
    lines = [f"  line {fr.lineno}: {fr.line}" for fr in tb if fr.filename == str(path)]
    exc = traceback.format_exception_only(*sys.exc_info()[:2])
    return "\n".join(lines + [l.rstrip() for l in exc])


def _err_line(path: Path) -> Optional[int]:
    tb = traceback.extract_tb(sys.exc_info()[2])
    for fr in reversed(tb):
        if fr.filename == str(path):
            return fr.lineno
    e = sys.exc_info()[1]
    if isinstance(e, SyntaxError) and e.filename == str(path):
        return e.lineno
    return None


def quick(path: str | Path, **params) -> Built:
    """One-liner: load, build, inspect, check."""
    return build_part(load_part(path), params or None)
