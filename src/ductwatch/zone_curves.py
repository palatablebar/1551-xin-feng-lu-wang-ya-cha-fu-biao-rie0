"""Compatibility entry point for zone calibration curve selection.

The canonical implementation lives in :mod:`ductwatch.fan_replay.service`
and :mod:`ductwatch.fan_replay.zone_curves`.
"""
from .fan_replay.zone_curves import *  # noqa: F401,F403
from .fan_replay import zone_curves as _impl

__all__ = _impl.__all__
