"""Integrations through the API: connectors, CRUD with the role matrix, deliveries, retry,
test sends, backfill requests."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range

from shared.bus import RedisStreamsBus, Topic
from shared.enums import Role
from shared.integrations.base import (
    LoginResult,
    PermanentFailure,
    SubjectChoice,
    SubjectOptions,
    SubjectStatus,
)
from shared.integrations.connectors.wildlifenl import WildlifeNlConnector
from shared.integrations.deliveries import enqueue, event_ref
from shared.integrations.deployments import compare
from shared.integrations.registry import CONNECTORS
from shared.models import (
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Event,
    Integration,
    IntegrationDelivery,
    IntegrationSubject,
)
from shared.secrets import decrypt_json
from tests.api.conftest import actor, create_project, project_actor

pytestmark = pytest.mark.asyncio


async def test_integration_lifecycle(client, db, monkeypatch):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}/integrations"

    connectors = (await client.get(f"{base}/connectors", headers=h)).json()
    keys = {c["key"] for c in connectors}
    assert keys >= {"gundi", "webhook", "mqtt"}
    assert all("config_schema" in c and "supports" in c for c in connectors)

    created = await client.post(
        base,
        json={
            "name": "Ops hook",
            "connector_key": "webhook",
            "config": {"url": "https://example.org/hook"},
            "credentials": {"secret": "s"},
            "object_types": ["position", "event"],
            "event_types": ["geofence_exit"],
            "min_severity": "warning",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    integration = created.json()
    assert integration["has_credentials"] and integration["event_types"] == ["GEOFENCE_EXIT"]
    assert "credentials" not in integration
    bad = await client.post(base, json={"name": "x", "connector_key": "nope"}, headers=h)
    assert bad.status_code == 422
    unsupported = await client.post(
        base,
        json={"name": "y", "connector_key": "gundi", "object_types": ["measurement"]},
        headers=h,
    )
    assert unsupported.status_code == 422
    duplicate = await client.post(
        base, json={"name": "Ops hook", "connector_key": "webhook"}, headers=h
    )
    assert duplicate.status_code == 409

    listed = (await client.get(base, headers=h)).json()
    assert [i["name"] for i in listed["items"]] == ["Ops hook"]
    detail = (await client.get(f"{base}/{integration['id']}", headers=h)).json()
    assert detail["counts"]["queued"] == 0 and detail["counts_24h"]["sent"] == 0

    patched = await client.patch(
        f"{base}/{integration['id']}",
        json={"enabled": False, "object_types": ["event"], "credentials": {"secret": "t"}},
        headers=h,
    )
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert patched.json()["object_types"] == ["event"]

    # viewers read, admins write
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(base, headers=viewer.headers)).status_code == 200
    assert (
        await client.post(
            base, json={"name": "v", "connector_key": "webhook"}, headers=viewer.headers
        )
    ).status_code == 403
    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    assert (
        await client.patch(
            f"{base}/{integration['id']}", json={"enabled": True}, headers=project_admin.headers
        )
    ).status_code == 200
    outsider = await actor(client, db)
    assert (await client.get(base, headers=outsider.headers)).status_code == 403

    # a test send goes to the target
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request)
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(**{"transport": httpx.MockTransport(handler), **kw}),
    )
    tested = await client.post(
        f"{base}/{integration['id']}/test",
        json={"latitude": -24.9, "longitude": 31.5},
        headers=h,
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] and posted[0].url.path == "/hook"
    assert "X-Protect-Signature" in posted[0].headers
    no_location = await client.post(f"{base}/{integration['id']}/test", json={}, headers=h)
    assert no_location.status_code == 200  # the webhook accepts a test without coordinates

    deleted = await client.delete(f"{base}/{integration['id']}", headers=h)
    assert deleted.status_code == 204
    assert (await client.get(f"{base}/{integration['id']}", headers=h)).status_code == 404


async def test_deliveries_retry_and_backfill(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}/integrations"
    integration = Integration(
        project_id=project.id,
        name="Hook",
        connector_key="webhook",
        config={"url": "https://example.org/x"},
        object_types=["event"],
        max_object_age_seconds=365 * 86_400,
    )
    event = Event(
        time=datetime.now(UTC) - timedelta(hours=1),
        project_id=project.id,
        event_type="BATTERY_LOW",
        severity="warning",
        title="Battery",
        context={},
    )
    db.add_all([integration, event])
    await db.commit()
    await enqueue(db, [integration], [event_ref(event)])
    await db.commit()
    delivery = await db.scalar(
        select(IntegrationDelivery).where(IntegrationDelivery.integration_id == integration.id)
    )
    assert delivery is not None
    listed = (await client.get(f"{base}/deliveries", headers=h)).json()
    assert len(listed["items"]) == 1 and listed["items"][0]["status"] == "queued"
    assert "request" not in listed["items"][0]
    filtered = (await client.get(f"{base}/deliveries", params={"status": "sent"}, headers=h)).json()
    assert filtered["items"] == []
    by_integration = (
        await client.get(
            f"{base}/deliveries", params={"integration_id": str(uuid.uuid4())}, headers=h
        )
    ).json()
    assert by_integration["items"] == []
    detail = (await client.get(f"{base}/deliveries/{delivery.id}", headers=h)).json()
    assert detail["response"] == {} and detail["object_type"] == "event"

    row = await db.get(IntegrationDelivery, delivery.id)
    row.status = "failed"
    row.error_message = "boom"
    await db.commit()
    retried = await client.post(f"{base}/deliveries/{delivery.id}/retry", headers=h)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["origin"] == "retry"
    row = await db.get(IntegrationDelivery, delivery.id)
    await db.refresh(row)
    row.status = "sent"
    await db.commit()
    assert (
        await client.post(f"{base}/deliveries/{delivery.id}/retry", headers=h)
    ).status_code == 409

    bus = RedisStreamsBus()
    try:
        before = await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED)
        requested = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "time_to": datetime.now(UTC).isoformat(),
            },
            headers=h,
        )
        assert requested.status_code == 200, requested.text
        assert requested.json()["backfill"]["status"] == "queued"
        assert await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED) == before + 1
        again = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "time_to": datetime.now(UTC).isoformat(),
            },
            headers=h,
        )
        assert again.status_code == 409
        reversed_range = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": datetime.now(UTC).isoformat(),
                "time_to": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            },
            headers=h,
        )
        assert reversed_range.status_code == 422
    finally:
        await bus.close()


class _Registrar:
    """A target with a register of entities, in place of the WildlifeNL connector's network."""

    key = "wildlifenl"
    label = "WildlifeNL"
    supports = frozenset({"position"})

    def __init__(self) -> None:
        self.registered: dict[uuid.UUID, dict] = {}
        self.deployed: list[tuple[str, str, datetime]] = []

    async def options(self, integration, subject):
        if integration.credentials.get("token") != "tok":
            raise PermanentFailure("the account lacks the herd-manager role")
        return SubjectOptions(
            sensor_id=subject.device_identity or "70B3D57ED0000012",
            status=SubjectStatus(subject.entity_id in self.registered),
            species=[SubjectChoice(id=BOS, name="Bos taurus", common_name="Rund")],
            proposed_species_id=None,
        )

    async def statuses(self, integration, subjects):
        return {
            s.entity_id: SubjectStatus(s.entity_id in self.registered, external_name=s.entity_name)
            for s in subjects
        }

    def sensor(self, integration, subject):
        return subject.device_name

    async def register_animal(self, integration, subject, settings):
        self.registered[subject.entity_id] = settings
        return f"animal-{len(self.registered)}"

    async def deploy(self, integration, animal_id, sensor_id, start):
        self.deployed.append((animal_id, sensor_id, start))


BOS = "44444444-4444-4444-8444-444444444444"


async def test_an_entity_is_integrated_from_its_own_page(client, db, monkeypatch):
    """Decisions D412 and D413: the entity sees the integrations it can join, a user with the
    right to change integrations picks its species from the target's list and integrates it,
    with its history first or at once; a viewer reads its state and changes nothing."""
    registrar = _Registrar()
    monkeypatch.setitem(CONNECTORS, "wildlifenl", registrar)
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    stranger = await project_actor(client, db, await create_project(db), Role.PROJECT_ADMIN)
    types = (
        await client.get("/api/v1/entity-types", params={"limit": 500}, headers=admin.headers)
    ).json()["items"]
    cow = next(t for t in types if t["key"] == "cow")
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": cow["id"], "name": "Cow 12"},
            headers=manager.headers,
        )
    ).json()
    base = f"/api/v1/projects/{project.id}/integrations"
    by_entity = f"{base}/by-entity/{entity['id']}"

    # no integration yet: the entity's card has nothing to show
    assert (await client.get(by_entity, headers=viewer.headers)).json() == []
    for name, connector in (("WildlifeNL test", "wildlifenl"), ("Hook", "webhook")):
        made = await client.post(
            base,
            json={
                "name": name,
                "connector_key": connector,
                "config": {"base_url": "https://wildlifenl.example", "url": "https://x.example"},
                "credentials": {"token": "tok"},
                "object_types": ["position"],
            },
            headers=manager.headers,
        )
        assert made.status_code == 201, made.text
        if connector == "wildlifenl":
            integration = made.json()
    # the one that registers its entities shows, the webhook does not
    listed = (await client.get(by_entity, headers=viewer.headers)).json()
    assert [(i["name"], i["subject"]) for i in listed] == [("WildlifeNL test", None)]
    assert (await client.get(by_entity, headers=stranger.headers)).status_code in (403, 404)

    subject = f"{base}/{integration['id']}/subjects/{entity['id']}"
    options = await client.get(f"{subject}/options", headers=manager.headers)
    assert options.status_code == 200, options.text
    offered = options.json()
    assert offered["species"] == [{"id": BOS, "name": "Bos taurus", "common_name": "Rund"}]
    assert offered["proposed_species_id"] is None and offered["subject"] is None
    assert offered["sensor_id"] == "70B3D57ED0000012" and offered["target"]["registered"] is False
    assert (await client.get(f"{subject}/options", headers=viewer.headers)).status_code == 403
    chosen = {"species_id": BOS, "species_name": "Bos taurus"}
    assert (await client.put(subject, json=chosen, headers=viewer.headers)).status_code == 403
    assert (await client.put(subject, json={}, headers=manager.headers)).status_code == 422

    # with its history first: asked on the bus, registered by the worker afterwards
    bus = RedisStreamsBus()
    try:
        before = await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED)
        too_far = (datetime.now(UTC) - timedelta(days=500)).isoformat()
        far = await client.put(
            subject, json={**chosen, "history_from": too_far}, headers=manager.headers
        )
        assert far.status_code == 422 and "400 days" in far.text
        since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        asked = await client.put(
            subject, json={**chosen, "history_from": since}, headers=manager.headers
        )
        assert asked.status_code == 200, asked.text
        assert asked.json()["state"] == "history_requested" and not registrar.registered
        assert await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED) == before + 1
    finally:
        await bus.close()
    stored = await db.get(Integration, uuid.UUID(integration["id"]))
    await db.refresh(stored)
    assert stored.entity_ids == [entity["id"]]  # forwarded from now on
    busy = await client.put(subject, json=chosen, headers=manager.headers)
    assert busy.status_code == 422 and "history is being sent" in busy.text

    # the entity's card and the integration's overview say where it stands
    card = (await client.get(by_entity, headers=viewer.headers)).json()[0]["subject"]
    assert card["state"] == "history_requested" and card["species_name"] == "Bos taurus"
    overview = await client.get(f"{base}/{integration['id']}/subjects", headers=manager.headers)
    assert overview.status_code == 200, overview.text
    (row,) = overview.json()["items"]
    assert row["entity_name"] == "Cow 12" and row["target"]["registered"] is False
    assert (
        await client.get(f"{base}/{integration['id']}/subjects", headers=viewer.headers)
    ).status_code == 403

    # stopped, then integrated at once without history
    assert (await client.delete(subject, headers=viewer.headers)).status_code == 403
    assert (await client.delete(subject, headers=manager.headers)).status_code == 204
    assert (await client.delete(subject, headers=manager.headers)).status_code == 404
    await db.refresh(stored)
    assert stored.entity_ids == []
    now = await client.put(subject, json=chosen, headers=manager.headers)
    assert now.status_code == 200, now.text
    assert now.json()["state"] == "registered" and now.json()["external_id"] == "animal-1"
    assert registrar.registered == {uuid.UUID(entity["id"]): chosen}

    # an integration that registers nothing has no subjects
    hook = next(
        i
        for i in (await client.get(base, headers=manager.headers)).json()["items"]
        if i["connector_key"] == "webhook"
    )
    refused = await client.put(
        f"{base}/{hook['id']}/subjects/{entity['id']}", json=chosen, headers=manager.headers
    )
    assert refused.status_code == 422 and "keeps no register" in refused.text


async def test_a_moved_device_is_confirmed_from_the_entity_or_the_device(client, db, monkeypatch):
    """Decisions D416 to D418: a device moved from one integrated entity to another shows as
    a deployment to confirm on both entities, on the device and on the integration's overview;
    a project admin confirms or declines it, a viewer reads it and changes nothing."""
    registrar = _Registrar()
    monkeypatch.setitem(CONNECTORS, "wildlifenl", registrar)
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    stranger = await project_actor(client, db, await create_project(db), Role.PROJECT_ADMIN)
    types = (
        await client.get("/api/v1/entity-types", params={"limit": 500}, headers=admin.headers)
    ).json()["items"]
    cow = next(t for t in types if t["key"] == "cow")
    base = f"/api/v1/projects/{project.id}/integrations"
    cows = [
        (
            await client.post(
                f"/api/v1/projects/{project.id}/entities",
                json={"entity_type_id": cow["id"], "name": name},
                headers=manager.headers,
            )
        ).json()
        for name in ("Cow 12", "Cow 13")
    ]
    device_type = DeviceType(
        key=f"t_{uuid.uuid4().hex[:8]}", label="Tag", driver_key="generic_json"
    )
    db.add(device_type)
    await db.flush()
    device = Device(name=f"SP-{uuid.uuid4().hex[:6]}", device_type_id=device_type.id)
    db.add(device)
    await db.flush()
    start = datetime.now(UTC) - timedelta(days=10)
    moved = datetime.now(UTC) - timedelta(days=1)
    db.add_all(
        [
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project.id,
                validity=Range(start, None, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=uuid.UUID(cows[0]["id"]),
                validity=Range(start, moved, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=uuid.UUID(cows[1]["id"]),
                validity=Range(moved, None, bounds="[)"),
            ),
        ]
    )
    await db.commit()
    integration = (
        await client.post(
            base,
            json={
                "name": "WildlifeNL test",
                "connector_key": "wildlifenl",
                "config": {"base_url": "https://wildlifenl.example"},
                "credentials": {"token": "tok"},
                "object_types": ["position"],
            },
            headers=manager.headers,
        )
    ).json()
    chosen = {"species_id": BOS, "species_name": "Bos taurus"}
    by_device = f"{base}/by-device/{device.id}"
    # the device's card: the entity it is on now, not integrated yet
    (seen,) = (await client.get(by_device, headers=viewer.headers)).json()
    assert seen["entity_name"] == "Cow 13" and seen["subject"] is None
    assert seen["deployments"] == []
    assert (await client.get(by_device, headers=stranger.headers)).status_code in (403, 404)

    for cow_row in cows:
        made = await client.put(
            f"{base}/{integration['id']}/subjects/{cow_row['id']}",
            json=chosen,
            headers=manager.headers,
        )
        assert made.json()["state"] == "registered", made.text
    # Cow 13 has the device now: its deployment was made by integrating it
    assert registrar.deployed == [("animal-2", device.name, moved)]

    # the device goes back to Cow 12 at the next hour: Protect asks first
    back = datetime.now(UTC)
    await db.execute(
        delete(DeviceEntityAssignment).where(
            DeviceEntityAssignment.device_id == device.id,
            DeviceEntityAssignment.entity_id == uuid.UUID(cows[1]["id"]),
        )
    )
    db.add_all(
        [
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=uuid.UUID(cows[1]["id"]),
                validity=Range(moved, back, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=uuid.UUID(cows[0]["id"]),
                validity=Range(back, None, bounds="[)"),
            ),
        ]
    )
    await db.commit()
    assert await compare(db) == {"pending": 1}

    (seen,) = (await client.get(by_device, headers=viewer.headers)).json()
    assert seen["entity_name"] == "Cow 12" and seen["subject"]["state"] == "registered"
    newest, before = seen["deployments"]
    assert (newest["entity_name"], newest["state"]) == ("Cow 12", "pending")
    assert newest["rewrites"] == 0 and newest["sensor_id"] == device.name
    assert (before["entity_name"], before["state"], before["open_on_target"]) == (
        "Cow 13",
        "sent",
        True,  # the target keeps it there until the new one is sent
    )
    card = (await client.get(f"{base}/by-entity/{cows[0]['id']}", headers=viewer.headers)).json()
    assert [d["state"] for d in card[0]["deployments"]] == ["pending"]
    overview = (
        await client.get(f"{base}/{integration['id']}/subjects", headers=manager.headers)
    ).json()
    assert [d["entity_name"] for d in overview["waiting"]] == ["Cow 12"]

    action = f"{base}/{integration['id']}/deployments/{newest['id']}"
    assert (await client.post(f"{action}/confirm", headers=viewer.headers)).status_code == 403
    assert (
        await client.post(
            f"{base}/{integration['id']}/deployments/{uuid.uuid4()}/confirm",
            headers=manager.headers,
        )
    ).status_code == 404
    done = await client.post(f"{action}/confirm", headers=manager.headers)
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "sent" and done.json()["open_on_target"] is True
    assert registrar.deployed[-1][:2] == ("animal-1", device.name)
    again = await client.post(f"{action}/decline", headers=manager.headers)
    assert again.status_code == 422 and "waits or was refused" in again.text
    (seen,) = (await client.get(by_device, headers=viewer.headers)).json()
    assert [d["open_on_target"] for d in seen["deployments"]] == [True, False]


async def test_an_integration_is_signed_in_with_a_code_from_the_email(client, db, monkeypatch):
    """Decision D414: the address, then the code; Protect stores what the target gives and
    shows the account, never the token."""
    asked: list[str] = []

    class _Login(WildlifeNlConnector):
        async def request_code(self, integration, email):
            asked.append(email)

        async def exchange_code(self, integration, email, code):
            if code != "123456":
                raise PermanentFailure("the target did not accept the code")
            return LoginResult({"token": "tok-secret"}, account=email, scopes=["data-system"])

    monkeypatch.setitem(CONNECTORS, "wildlifenl", _Login())
    await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    base = f"/api/v1/projects/{project.id}/integrations"
    connectors = {
        c["key"]: c
        for c in (await client.get(f"{base}/connectors", headers=manager.headers)).json()
    }
    assert connectors["wildlifenl"]["login"] == "email_code"
    assert connectors["webhook"]["login"] is None

    # made without credentials: the sign-in fills them
    made = await client.post(
        base,
        json={
            "name": "WildlifeNL test",
            "connector_key": "wildlifenl",
            "config": {"base_url": "https://wildlifenl.example"},
            "object_types": ["position"],
        },
        headers=manager.headers,
    )
    assert made.status_code == 201 and made.json()["has_credentials"] is False
    login = f"{base}/{made.json()['id']}/login"
    email = {"email": "tim@example.org"}

    refused = await client.post(f"{login}/code", json=email, headers=viewer.headers)
    assert refused.status_code == 403
    bad = await client.post(f"{login}/code", json={"email": "no address"}, headers=manager.headers)
    assert bad.status_code == 422
    sent = await client.post(f"{login}/code", json=email, headers=manager.headers)
    assert sent.status_code == 204 and asked == ["tim@example.org"]

    wrong = await client.post(login, json={**email, "code": "000000"}, headers=manager.headers)
    assert wrong.status_code == 422 and "did not accept the code" in wrong.text
    assert (
        await client.post(login, json={**email, "code": "123456"}, headers=viewer.headers)
    ).status_code == 403
    done = await client.post(login, json={**email, "code": "123456"}, headers=manager.headers)
    assert done.status_code == 200, done.text
    assert done.json() == {"account": "tim@example.org", "scopes": ["data-system"]}

    read = (await client.get(f"{base}/{made.json()['id']}", headers=manager.headers)).json()
    assert read["has_credentials"] is True and read["config"]["account"] == "tim@example.org"
    assert "tok-secret" not in str(read)  # the token is the server's own
    stored = await db.get(Integration, uuid.UUID(made.json()["id"]))
    await db.refresh(stored)
    assert decrypt_json(stored.credentials_encrypted) == {"token": "tok-secret"}

    # the platform's two servers are offered by name, with a plain sentence for people (D415)
    assert [(s["label"], s["base_url"]) for s in connectors["wildlifenl"]["servers"]] == [
        ("Test", "https://test-api-wildlifenl.uu.nl"),
        ("Live", "https://live-api-wildlifenl.uu.nl"),
    ]
    assert connectors["wildlifenl"]["intro"] and connectors["webhook"]["servers"] == []

    # a form cannot write who is signed in, and saving the same server keeps the sign-in
    one = f"{base}/{made.json()['id']}"
    same = await client.patch(
        one,
        json={"config": {"base_url": "https://wildlifenl.example", "account": "someone@else.org"}},
        headers=manager.headers,
    )
    assert same.status_code == 200, same.text
    assert same.json()["config"]["account"] == "tim@example.org" and same.json()["has_credentials"]

    # another server is refused while an entity is integrated with this one
    admin = await actor(client, db, superuser=True)
    types = (
        await client.get("/api/v1/entity-types", params={"limit": 500}, headers=admin.headers)
    ).json()["items"]
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": next(t for t in types if t["key"] == "cow")["id"], "name": "C"},
            headers=manager.headers,
        )
    ).json()
    db.add(
        IntegrationSubject(
            integration_id=uuid.UUID(made.json()["id"]),
            entity_id=uuid.UUID(entity["id"]),
            state="registered",
        )
    )
    await db.commit()
    live = {"config": {"base_url": "https://live.example"}}
    held = await client.patch(one, json=live, headers=manager.headers)
    assert held.status_code == 409 and "second integration" in held.text
    await db.execute(delete(IntegrationSubject))
    await db.commit()
    # and with none integrated it signs the integration out: the other server never saw it
    moved = await client.patch(one, json=live, headers=manager.headers)
    assert moved.status_code == 200, moved.text
    assert moved.json()["has_credentials"] is False and "account" not in moved.json()["config"]

    # a connector without such a sign-in says so
    hook = await client.post(
        base,
        json={"name": "Hook", "connector_key": "webhook", "config": {"url": "https://x.example"}},
        headers=manager.headers,
    )
    none = await client.post(
        f"{base}/{hook.json()['id']}/login/code", json=email, headers=manager.headers
    )
    assert none.status_code == 422 and "no sign-in" in none.text
