"""The modules: the two of phase 1, device performance (phase 28), contact tracing (phase 31)
and the cardiac study (phase 34). Importing this package registers them in the catalogue. The
worker and the API import it; nothing in the core does."""

from __future__ import annotations

from shared.analysis import register
from shared.analysis.modules.cardiac import CardiacModule
from shared.analysis.modules.contact_tracing import ContactTracingModule
from shared.analysis.modules.device_performance import DevicePerformanceModule
from shared.analysis.modules.grazing import GrazingModule
from shared.analysis.modules.movement import MovementModule

register(MovementModule())
register(GrazingModule())
register(DevicePerformanceModule())
register(ContactTracingModule())
register(CardiacModule())

__all__ = ["CardiacModule", "DevicePerformanceModule", "GrazingModule", "MovementModule"]
