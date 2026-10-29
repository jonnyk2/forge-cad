"""Forge — AI-native parametric CAD for parts that get made.

A part file does ``from forge import *`` and gets build123d's whole API plus
the forge layer: Param/ParamSet, FDM/CNC, manufacturing-aware features, and
the standard-parts library.
"""
from build123d import *  # noqa: F401,F403  — the kernel API is the API

from .params import Param, ParamSet, mm, deg, count  # noqa: F401
from .dfm.base import FDM, CNC, EndMill, Violation  # noqa: F401
from .features import (  # noqa: F401
    screw_hole, pin_hole, magnet_pocket, bearing_pocket, heatset_boss,
    teardrop_hole, elephant_foot_chamfer, fit_diameter, screw_diameter, text_depth,
)
from . import library  # noqa: F401
from .library import screw, heatset, bearing, magnet, fdm_guidance  # noqa: F401
from .part import load_part, build_part, quick, PartError, Built  # noqa: F401
from .inspect import inspect, Report  # noqa: F401
from .export import export, drawing  # noqa: F401
from .render import render, section  # noqa: F401
from . import orient  # noqa: F401

__version__ = "0.3.1"

__all__ = [n for n in dir() if not n.startswith("_")]
