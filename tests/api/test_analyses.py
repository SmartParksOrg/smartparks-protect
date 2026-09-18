"""The analysis API (docs/ANALYTICS_PHASE1_PLAN.md, section 12) with a stub module: the
catalogue, the estimate, the run's life through the worker's runner, the scope, the bounds,
the flags and the exports."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from shared.analysis import MODULES
from shared.analysis.base import (
    Geometry,
    Period,
    Provenance,
    ResultDocument,
    RunContext,
    RunResult,
    Subject,
    Table,
)
from shared.analysis.parameters import CommonParameters
from shared.analysis.runner import run_analysis
from shared.config import get_settings
from shared.enums import Role
from shared.models import AnalysisRun, Group, ProjectMembership
from tests.api.conftest import actor, create_project, create_user, login, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

FROM = datetime(2026, 9, 1, tzinfo=UTC)
TO = datetime(2026, 9, 8, tzinfo=UTC)


class StubParameters(CommonParameters):
    note: str = ""


class StubModule:
    key = "movement"
    label = "Movement (stub)"
    version = "stub/1"
    parameters = StubParameters

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, StubParameters)
        await ctx.progress(50, "half")
        subjects = [Subject(id=i, name=str(i)[:8]) for i in params.entity_ids]
        period = Period(time_from=params.time_from, time_to=params.time_to)
        document = ResultDocument(
            module="movement",
            method_version="stub/1",
            subjects=subjects,
            periods=[period],
            summary={"subjects": len(subjects)},
            tables=[
                Table(
                    key="summary",
                    columns=["subject", "distance_km"],
                    rows=[[s.name, 1.5] for s in subjects],
                )
            ],
            geometries={"mcp": len(subjects)},
            provenance=Provenance(
                module="movement",
                method_version="stub/1",
                subjects=subjects,
                periods=[period],
                parameters=params.model_dump(mode="json"),
                input_count=0,
                excluded_count=0,
                computed_at=datetime.now(UTC),
            ),
        )
        square = {
            "type": "Polygon",
            "coordinates": [
                [[5.36, 52.09], [5.37, 52.09], [5.37, 52.10], [5.36, 52.10], [5.36, 52.09]]
            ],
        }
        return RunResult(
            document=document,
            geometries=[
                Geometry(
                    kind="mcp", subject_id=s.id, label=f"MCP {s.name}", level=0.95, geojson=square
                )
                for s in subjects
            ],
        )


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setitem(MODULES, "movement", StubModule())


async def _entities(client, h, project, names, group_id=None):
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
            },
            headers=h,
        )
    ).json()
    ids = []
    for name in names:
        body = {"entity_type_id": entity_type["id"], "name": name}
        if group_id:
            body["group_id"] = group_id
        created = await client.post(f"/api/v1/projects/{project.id}/entities", json=body, headers=h)
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return entity_type["id"], ids


def _params(entity_ids=None, **extra):
    body = {"time_from": FROM.isoformat(), "time_to": TO.isoformat(), **extra}
    if entity_ids is not None:
        body["entity_ids"] = entity_ids
    return body


async def test_catalogue_estimate_and_the_life_of_a_run(client, db, stub):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    _, ids = await _entities(client, h, project, ["Wolf 1", "Wolf 2"])
    base = f"/api/v1/projects/{project.id}/analyses"

    catalogue = (await client.get("/api/v1/analysis-modules", headers=h)).json()
    assert [m["key"] for m in catalogue] == [
        "movement",
        "grazing",
        "device_performance",
        "contact_tracing",
    ]
    assert catalogue[0]["limits"]["subjects"] == 25 and catalogue[0]["limits"]["days"] == 366

    estimate = await client.get(
        f"{base}/estimate",
        params={"module": "movement", "parameters": json.dumps(_params(ids))},
        headers=h,
    )
    assert estimate.status_code == 200, estimate.text
    assert (
        estimate.json()["subjects"] == 2 and estimate.json()["fixes"] == 0 and estimate.json()["ok"]
    )

    created = await client.post(
        base, json={"module": "movement", "parameters": _params(ids)}, headers=h
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "queued" and run["method_version"] == "stub/1"
    assert set(run["parameters"]["entity_ids"]) == set(ids)

    # the worker's runner, called here as the worker would
    row = await db.get(AnalysisRun, uuid.UUID(run["id"]))
    await run_analysis(db, row)
    detail = (await client.get(f"{base}/{run['id']}", headers=h)).json()
    assert detail["status"] == "completed" and detail["progress"] == 100
    assert detail["result"]["summary"] == {"subjects": 2}
    listed = (await client.get(base, headers=h)).json()["items"]
    assert [r["id"] for r in listed] == [run["id"]] and listed[0]["result"] is None

    geometries = (
        await client.get(f"{base}/{run['id']}/geometries", params={"kind": "mcp"}, headers=h)
    ).json()
    assert geometries["type"] == "FeatureCollection" and len(geometries["features"]) == 2
    assert geometries["features"][0]["properties"]["area_m2"] > 0

    document = await client.get(
        f"{base}/{run['id']}/export", params={"what": "document"}, headers=h
    )
    assert document.status_code == 200 and document.json()["module"] == "movement"
    table = await client.get(
        f"{base}/{run['id']}/export", params={"what": "summary", "format": "csv"}, headers=h
    )
    assert table.status_code == 200 and table.text.splitlines()[0] == "subject,distance_km"
    geojson = await client.get(
        f"{base}/{run['id']}/export", params={"what": "geometries", "format": "geojson"}, headers=h
    )
    assert geojson.status_code == 200 and geojson.json()["features"]

    kept = await client.patch(f"{base}/{run['id']}", json={"name": "Wolves, week one"}, headers=h)
    assert kept.status_code == 200 and kept.json()["expires_at"] is None
    assert kept.json()["created_by_name"] == admin.user.email and kept.json()["shared"] is False

    # a run is the runner's own until shared with the project
    other = await project_actor(client, db, project, Role.PROJECT_ANALYST)
    assert (await client.get(f"{base}/{run['id']}", headers=other.headers)).status_code == 404
    assert run["id"] not in {
        r["id"] for r in (await client.get(base, headers=other.headers)).json()["items"]
    }
    shared = await client.patch(f"{base}/{run['id']}", json={"shared": True}, headers=h)
    assert shared.status_code == 200 and shared.json()["shared"] is True
    assert shared.json()["name"] == "Wolves, week one"  # a field left out stays
    seen = await client.get(f"{base}/{run['id']}", headers=other.headers)
    assert seen.status_code == 200 and seen.json()["created_by_name"] == admin.user.email
    # the other member may not rename or delete it
    assert (
        await client.patch(f"{base}/{run['id']}", json={"name": "Mine"}, headers=other.headers)
    ).status_code == 403

    # a queued run can be cancelled and deleted
    again = await client.post(
        base, json={"module": "movement", "parameters": _params(ids)}, headers=h
    )
    assert again.status_code == 201
    cancelled = await client.post(f"{base}/{again.json()['id']}/cancel", headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await client.delete(f"{base}/{again.json()['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{base}/{again.json()['id']}", headers=h)).status_code == 404


async def test_subjects_from_a_group_and_a_type_and_the_bounds(client, db, stub):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    group = Group(project_id=project.id, name=unique_name("Herd"))
    db.add(group)
    await db.commit()
    type_id, in_group = await _entities(client, h, project, ["A", "B"], group_id=str(group.id))
    _, loose = await _entities(client, h, project, ["C"])
    base = f"/api/v1/projects/{project.id}/analyses"

    by_group = await client.post(
        base, json={"module": "movement", "parameters": _params(group_id=str(group.id))}, headers=h
    )
    assert by_group.status_code == 201, by_group.text
    assert set(by_group.json()["parameters"]["entity_ids"]) == set(in_group)
    by_type = await client.post(
        base, json={"module": "movement", "parameters": _params(entity_type_id=type_id)}, headers=h
    )
    assert by_type.status_code == 201, by_type.text
    assert set(by_type.json()["parameters"]["entity_ids"]) == set(in_group)

    nothing = await client.post(
        base, json={"module": "movement", "parameters": _params()}, headers=h
    )
    assert nothing.status_code == 422
    unknown = await client.post(
        base, json={"module": "movement", "parameters": _params([str(uuid.uuid4())])}, headers=h
    )
    assert unknown.status_code == 422
    too_long = await client.post(
        base,
        json={
            "module": "movement",
            "parameters": {
                "entity_ids": loose,
                "time_from": FROM.isoformat(),
                "time_to": (FROM + timedelta(days=400)).isoformat(),
            },
        },
        headers=h,
    )
    assert too_long.status_code == 422
    backwards = await client.post(
        base,
        json={
            "module": "movement",
            "parameters": {
                "entity_ids": loose,
                "time_from": TO.isoformat(),
                "time_to": FROM.isoformat(),
            },
        },
        headers=h,
    )
    assert backwards.status_code == 422
    assert (
        await client.post(base, json={"module": "habitat", "parameters": _params(loose)}, headers=h)
    ).status_code == 404

    # the queue cap: two more queued runs reach it
    for _ in range(3):
        assert (
            await client.post(
                base, json={"module": "movement", "parameters": _params(loose)}, headers=h
            )
        ).status_code == 201
    capped = await client.post(
        base, json={"module": "movement", "parameters": _params(loose)}, headers=h
    )
    assert capped.status_code == 429


async def test_roles_scope_and_flags(client, db, stub, monkeypatch):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    _, ids = await _entities(client, h, project, ["Seen", "Unseen"])
    base = f"/api/v1/projects/{project.id}/analyses"

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (
        await client.post(
            base, json={"module": "movement", "parameters": _params(ids)}, headers=viewer.headers
        )
    ).status_code == 403
    assert (await client.get(base, headers=viewer.headers)).status_code == 200
    analyst = await project_actor(client, db, project, Role.PROJECT_ANALYST)
    mine = await client.post(
        base, json={"module": "movement", "parameters": _params(ids)}, headers=analyst.headers
    )
    assert mine.status_code == 201, mine.text
    # the analyst may not delete the admin's run (unseen while unshared, refused once shared),
    # the admin may delete the analyst's
    admins = await client.post(
        base, json={"module": "movement", "parameters": _params(ids[:1])}, headers=h
    )
    assert (
        await client.delete(f"{base}/{admins.json()['id']}", headers=analyst.headers)
    ).status_code == 404
    await client.patch(f"{base}/{admins.json()['id']}", json={"shared": True}, headers=h)
    assert (
        await client.delete(f"{base}/{admins.json()['id']}", headers=analyst.headers)
    ).status_code == 403
    assert (await client.delete(f"{base}/{mine.json()['id']}", headers=h)).status_code == 204

    # a member scoped to one entity: the other is refused, and a run over both is hidden
    scoped_user = await create_user(db)
    db.add(
        ProjectMembership(
            user_id=scoped_user.id,
            project_id=project.id,
            role=Role.PROJECT_ANALYST,
            scope={"groups": [], "entities": [ids[0]], "devices": []},
        )
    )
    await db.commit()
    scoped = {"Authorization": f"Bearer {await login(client, scoped_user.email)}"}
    assert (
        await client.post(
            base, json={"module": "movement", "parameters": _params(ids)}, headers=scoped
        )
    ).status_code == 422
    own = await client.post(
        base, json={"module": "movement", "parameters": _params(ids[:1])}, headers=scoped
    )
    assert own.status_code == 201, own.text
    visible = {r["id"] for r in (await client.get(base, headers=scoped)).json()["items"]}
    assert own.json()["id"] in visible and admins.json()["id"] in visible
    both = await client.post(
        base, json={"module": "movement", "parameters": _params(ids)}, headers=h
    )
    assert both.json()["id"] not in {
        r["id"] for r in (await client.get(base, headers=scoped)).json()["items"]
    }
    assert (await client.get(f"{base}/{both.json()['id']}", headers=scoped)).status_code == 404

    # the project's own list narrows the deployment's
    off = await client.patch(
        f"/api/v1/projects/{project.id}", json={"settings": {"analysis_modules": []}}, headers=h
    )
    assert off.status_code == 200, off.text
    assert (
        await client.post(base, json={"module": "movement", "parameters": _params(ids)}, headers=h)
    ).status_code == 404
    projects = (await client.get("/api/v1/projects", headers=h)).json()["items"]
    assert next(p for p in projects if p["id"] == str(project.id))["analysis_modules"] == []
    # and the deployment's setting turns the module off everywhere
    await client.patch(f"/api/v1/projects/{project.id}", json={"settings": {}}, headers=h)
    monkeypatch.setattr(get_settings(), "analysis_modules", "grazing")
    assert [m["key"] for m in (await client.get("/api/v1/analysis-modules", headers=h)).json()] == [
        "grazing"
    ]
    assert (
        await client.post(base, json={"module": "movement", "parameters": _params(ids)}, headers=h)
    ).status_code == 404


async def test_every_module_can_reach_the_subject_limit_it_declares(client, db):
    """A module whose own cap differs from the router's table is a cap nobody can reach: the
    module would allow forty and the request would be refused at twenty-five. Contact tracing
    was exactly that until a real run hit it."""
    from protect_api.routers.analyses import SUBJECT_LIMITS
    from shared.analysis.limits import MAX_SUBJECTS_CONTACT

    admin = await actor(client, db, superuser=True)
    catalogue = (await client.get("/api/v1/analysis-modules", headers=admin.headers)).json()
    for module in catalogue:
        assert module["key"] in SUBJECT_LIMITS, (
            f"{module['key']} falls back to the movement limit, which may not be its own"
        )
    assert SUBJECT_LIMITS["contact_tracing"] == MAX_SUBJECTS_CONTACT


def test_every_registered_module_is_a_key_the_database_admits():
    """A run row's module is checked against `AnalysisModuleKey` in the database. A module that
    registers itself without an entry there reaches the catalogue, passes validation, and fails
    on the INSERT with a 500 — which is how contact tracing first behaved on the dev server."""
    from shared.analysis import MODULES
    from shared.enums import AnalysisModuleKey

    known = {k.value for k in AnalysisModuleKey}
    assert set(MODULES) <= known, (
        f"{sorted(set(MODULES) - known)} would be refused by ck_analysis_runs_module; "
        "add the key to AnalysisModuleKey and a migration that widens the check"
    )
