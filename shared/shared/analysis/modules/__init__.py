"""The phase 1 modules; importing this package registers them in the catalogue. The worker
and the API import it; nothing in the core does."""

from __future__ import annotations

from shared.analysis import register
from shared.analysis.modules.movement import MovementModule

register(MovementModule())

__all__ = ["MovementModule"]
