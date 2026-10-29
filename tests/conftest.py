"""If the CAD kernel isn't installed, stub `build123d` and `OCP` so the
kernel-free tests can still import forge.  Tests that need real geometry
are skipped via the `kernel` marker."""
import importlib
import importlib.abc
import importlib.machinery
import sys
import types

import pytest

try:
    import build123d  # noqa: F401
    HAVE_KERNEL = True
except ImportError:
    HAVE_KERNEL = False


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, n): return _Any()
    def __mul__(self, o): return _Any()
    def __iter__(self): return iter(())


def _make_module(name):
    m = types.ModuleType(name)
    m.__path__ = []
    m.__getattr__ = lambda attr: _Any  # any name resolves to a dummy class
    m.__all__ = []                       # `from build123d import *` imports nothing
    m.__version__ = "stub"
    return m


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in ("build123d", "OCP"):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return _make_module(spec.name)

    def exec_module(self, module):
        pass


if not HAVE_KERNEL:
    sys.meta_path.insert(0, _StubFinder())
    import matplotlib
    matplotlib.use("Agg")


def pytest_configure(config):
    config.addinivalue_line("markers", "kernel: needs build123d/OpenCascade installed")


def pytest_collection_modifyitems(config, items):
    if HAVE_KERNEL:
        return
    skip = pytest.mark.skip(reason="build123d not installed")
    for item in items:
        if "kernel" in item.keywords:
            item.add_marker(skip)
