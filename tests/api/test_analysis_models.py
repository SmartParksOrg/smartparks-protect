"""The analysis tables (docs/ANALYTICS_PHASE1_PLAN.md, section 6): a run and a geometry row
round-trip, the geometry's area comes from PostGIS, and the run's rows go with it."""

import uuid

import pytest
from geoalchemy2 import Geography
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import cast, func, select

from shared.models import AnalysisGeometry, AnalysisRun
from tests.api.conftest import create_project

pytestmark = pytest.mark.asyncio


async def test_run_and_geometry_round_trip(db):
    project = await create_project(db)
    run = AnalysisRun(
        project_id=project.id,
        module="movement",
        parameters={"entity_ids": [str(uuid.uuid4())]},
        method_version="movement/1",
    )
    db.add(run)
    await db.flush()
    square = Polygon([(5.36, 52.09), (5.37, 52.09), (5.37, 52.10), (5.36, 52.10), (5.36, 52.09)])
    db.add(
        AnalysisGeometry(
            run_id=run.id,
            kind="mcp",
            label="MCP 95",
            level=0.95,
            geom=from_shape(square, srid=4326),
            properties={"subject": "x"},
        )
    )
    await db.commit()

    stored = await db.get(AnalysisRun, run.id)
    assert stored is not None and stored.status == "queued" and stored.progress == 0
    hectares = await db.scalar(
        select(func.ST_Area(cast(AnalysisGeometry.geom, Geography)) / 10_000).where(
            AnalysisGeometry.run_id == run.id
        )
    )
    # a 0.01 by 0.01 degree square near 52 north: about 68 by 111 metres times 100, 75 ha
    assert hectares is not None and 70 < hectares < 80

    await db.delete(stored)
    await db.commit()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AnalysisGeometry)
            .where(AnalysisGeometry.run_id == run.id)
        )
    ) == 0
