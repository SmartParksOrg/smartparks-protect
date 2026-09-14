"""The analysis subsystem (phase 22 of the plan, docs/ANALYTICS_PHASE1_PLAN.md): computed results
over the core's tracking data, kept apart from the core. A module is code in `modules/`, a run
is a row, the worker of its own computes, and nothing in the core imports this package (a
test holds that boundary). Two modules in phase 1: movement ecology and grazing."""

from __future__ import annotations

from shared.analysis.base import AnalysisModule
from shared.config import Settings

#: The modules by key; the movement and grazing modules register themselves on import.
MODULES: dict[str, AnalysisModule] = {}


def register(module: AnalysisModule) -> AnalysisModule:
    MODULES[module.key] = module
    return module


def enabled_modules(settings: Settings) -> list[str]:
    """The module keys this deployment allows (`ANALYSIS_MODULES`, a comma list; empty
    disables every analysis), in the catalogue's order, unknown keys ignored."""
    wanted = {k.strip() for k in settings.analysis_modules.split(",") if k.strip()}
    return [key for key in MODULES if key in wanted]
