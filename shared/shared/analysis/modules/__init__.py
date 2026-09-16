"""The modules: the two of phase 1 and device performance (phase 28). Importing this package
registers them in the catalogue. The worker and the API import it; nothing in the core does."""

from __future__ import annotations

from shared.analysis import register
from shared.analysis.modules.device_performance import DevicePerformanceModule
from shared.analysis.modules.grazing import GrazingModule
from shared.analysis.modules.movement import MovementModule

register(MovementModule())
register(GrazingModule())
register(DevicePerformanceModule())

__all__ = ["DevicePerformanceModule", "GrazingModule", "MovementModule"]
