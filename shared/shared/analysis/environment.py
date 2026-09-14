"""The boundary for environmental data a later level may add (plan, section 11): a module asks
for a layer by name and gets values per geometry; it never names a provider. Phase 1 registers
no provider and calls none."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class LayerSample(BaseModel):
    """Values per geometry (in the order asked), or a time series per geometry, with where they
    came from and how fine they are."""

    layer: str
    source: str
    resolution: str | None = None
    sampled_at: datetime
    values: list[float | None] = Field(default_factory=list)
    series: list[list[tuple[datetime, float | None]]] = Field(default_factory=list)


class EnvironmentalDataProvider(Protocol):
    key: str
    layers: tuple[str, ...]

    async def sample(
        self,
        layer: str,
        geometries: Sequence[dict[str, Any]],
        time_from: datetime,
        time_to: datetime,
        project_id: uuid.UUID,
    ) -> LayerSample: ...


#: Providers in order of preference: a project-specific one first, an open global one after.
PROVIDERS: list[EnvironmentalDataProvider] = []


def provider_for(layer: str) -> EnvironmentalDataProvider | None:
    return next((p for p in PROVIDERS if layer in p.layers), None)
