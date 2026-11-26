"""兼容入口：实现见 :mod:`ductwatch.fan_replay.zone_curves` 与 ``service``。"""
from .zone_curves import *  # noqa: F401,F403
from . import zone_curves as _impl
__all__ = _impl.__all__
