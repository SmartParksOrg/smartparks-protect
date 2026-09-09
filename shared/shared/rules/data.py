"""History lookups for the evaluator, on SQLAlchemy. Live mode reads current-state tables for
`last_seen`; historical mode (replay) derives everything from the canonical rows before the
sample time, so a replay sees the world as it was."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.curation.effective import (
    before as effective_before,
)
from shared.curation.effective import (
    effective_geom,
    effective_number,
    effective_time,
    visible,
)
from shared.models import (
    DeviceCurrentState,
    Entity,
    EntityCurrentState,
    Feature,
    Measurement,
    Position,
)
from shared.rules.evaluator import EntityPoint, FeatureGeometry, Subject
from shared.timeutil import utc_now

LOOKBACK = timedelta(days=7)
FEATURE_CACHE_SECONDS = 60


def _subject_filter(model: type[Position] | type[Measurement], subject: Subject) -> Any:
    if subject.entity_id is not None:
        return model.entity_id == subject.entity_id
    return model.device_id == subject.device_id


class SqlDataAccess:
    def __init__(self, session: AsyncSession, *, historical: bool = False) -> None:
        self.session = session
        self.historical = historical
        self._features: dict[str, tuple[datetime, list[FeatureGeometry]]] = {}

    async def latest_value(self, subject: Subject, metric: str, before: datetime) -> float | None:
        row = await self.session.execute(
            select(effective_number())
            .where(
                _subject_filter(Measurement, subject),
                Measurement.metric_key == metric,
                effective_before(Measurement, before, before - LOOKBACK),
                visible(Measurement),
            )
            .order_by(effective_time(Measurement).desc())
            .limit(1)
        )
        result = row.scalar_one_or_none()
        return float(result) if result is not None else None

    async def entity_points(
        self, project_id: uuid.UUID, entity_ids: list[uuid.UUID], before: datetime
    ) -> list[EntityPoint]:
        """The latest positions of other entities of the project (the proximity condition,
        decision D140): the current state live, the newest position before the sample time in
        historical mode."""
        if not entity_ids:
            return []
        points: list[EntityPoint] = []
        if not self.historical:
            rows = (
                await self.session.execute(
                    select(
                        Entity.id,
                        Entity.name,
                        EntityCurrentState.latest_position,
                        EntityCurrentState.latest_position_time,
                    )
                    .join(EntityCurrentState, EntityCurrentState.entity_id == Entity.id)
                    .where(
                        Entity.id.in_(entity_ids),
                        Entity.project_id == project_id,
                        EntityCurrentState.latest_position.is_not(None),
                    )
                )
            ).all()
            for entity_id, name, geom, time in rows:
                shape = to_shape(geom)
                points.append(EntityPoint(entity_id, name, (shape.x, shape.y), time))
            return points
        names = {
            e.id: e.name
            for e in (
                await self.session.scalars(
                    select(Entity).where(Entity.id.in_(entity_ids), Entity.project_id == project_id)
                )
            ).all()
        }
        for entity_id, name in names.items():
            row = (
                await self.session.execute(
                    select(effective_geom(), effective_time(Position))
                    .where(
                        Position.entity_id == entity_id,
                        effective_before(Position, before, before - LOOKBACK),
                        visible(Position),
                    )
                    .order_by(effective_time(Position).desc())
                    .limit(1)
                )
            ).first()
            if row is not None:
                shape = to_shape(row[0])
                points.append(EntityPoint(entity_id, name, (shape.x, shape.y), row[1]))
        return points

    async def latest_point(
        self, subject: Subject, before: datetime
    ) -> tuple[tuple[float, float], datetime] | None:
        row = (
            await self.session.execute(
                select(effective_geom(), effective_time(Position))
                .where(
                    _subject_filter(Position, subject),
                    effective_before(Position, before, before - LOOKBACK),
                    visible(Position),
                )
                .order_by(effective_time(Position).desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        point = to_shape(row[0])
        return (point.x, point.y), row[1]

    async def window(
        self, subject: Subject, metric: str, aggregate: str, seconds: int, at: datetime
    ) -> float | None:
        value = effective_number()
        agg = {
            "avg": func.avg(value),
            "min": func.min(value),
            "max": func.max(value),
            "sum": func.sum(value),
            "count": func.count(value),
        }[aggregate]
        result = await self.session.scalar(
            select(agg).where(
                _subject_filter(Measurement, subject),
                Measurement.metric_key == metric,
                effective_before(Measurement, at, at - timedelta(seconds=seconds)),
                visible(Measurement),
            )
        )
        if result is None:
            return None
        return float(result)

    async def features(
        self, project_id: uuid.UUID, feature_ids: list[uuid.UUID], feature_type: str | None
    ) -> list[FeatureGeometry]:
        key = f"{project_id}|{','.join(sorted(map(str, feature_ids)))}|{feature_type}"
        cached = self._features.get(key)
        now = utc_now()
        if cached is not None and (
            self.historical or (now - cached[0]).total_seconds() < FEATURE_CACHE_SECONDS
        ):
            return cached[1]
        statement = select(Feature).where(Feature.project_id == project_id)
        if feature_ids:
            statement = statement.where(Feature.id.in_(feature_ids))
        elif feature_type is not None:
            statement = statement.where(Feature.feature_type == feature_type)
        rows = (await self.session.scalars(statement.order_by(Feature.name).limit(500))).all()
        features = [
            FeatureGeometry(
                id=f.id, name=f.name, feature_type=f.feature_type, geometry=to_shape(f.geom)
            )
            for f in rows
        ]
        self._features[key] = (now, features)
        return features

    async def last_seen(self, subject: Subject, at: datetime) -> datetime | None:
        if not self.historical:
            if subject.entity_id is not None:
                current = await self.session.get(EntityCurrentState, subject.entity_id)
                return current.last_seen_at if current is not None else None
            device = await self.session.get(DeviceCurrentState, subject.device_id)
            return device.last_seen_at if device is not None else None
        since = at - timedelta(days=90)
        latest_position = await self.session.scalar(
            select(func.max(effective_time(Position))).where(
                _subject_filter(Position, subject),
                effective_before(Position, at, since),
                visible(Position),
            )
        )
        latest_measurement = await self.session.scalar(
            select(func.max(effective_time(Measurement))).where(
                _subject_filter(Measurement, subject),
                effective_before(Measurement, at, since),
                visible(Measurement),
            )
        )
        candidates = [t for t in (latest_position, latest_measurement) if t is not None]
        return max(candidates) if candidates else None
