"""AddaxAI Connect connector: image filters, the detection event, login and the cursor."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.addaxai_connect import (
    AddaxAiConnectAdapter,
    AddaxAiConnector,
    AddaxAiManagement,
    detections_of,
    parse_image,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext, MemoryCursorStore
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "addaxai_connect"
PAGE = json.loads((FIXTURES / "images_page.json").read_text())
CAMERAS = {c["id"]: c for c in json.loads((FIXTURES / "cameras.json").read_text())}


def _source(config=None, credentials=None, cursors=None):
    return DataSourceContext(
        id=uuid.uuid4(),
        name="Connect",
        adapter_key="addaxai_connect",
        config={"url": "https://connect.example.org", **(config or {})},
        credentials=credentials
        if credentials is not None
        else {"email": "bot@example.org", "password": "pw"},
        capabilities=AdapterCapabilities(uplink=True),
        cursors=cursors,
    )


def test_detection_filters():
    wolf, person, fox = PAGE["items"]
    assert [d["category"] for d in detections_of(wolf, _source())] == ["animal"]
    assert detections_of(fox, _source()) == []  # 0.31 below the default 0.5
    assert len(detections_of(fox, _source({"min_confidence": 0.2}))) == 1
    assert detections_of(person, _source({"categories": ["animal"]})) == []
    assert len(detections_of(person, _source({"categories": ["person"]}))) == 1
    assert detections_of(wolf, _source({"species": ["red_fox"]})) == []
    assert len(detections_of(wolf, _source({"species": ["Wolf"]}))) == 1


def test_image_becomes_detection_event():
    wolf = PAGE["items"][0]
    message = parse_image(_source(), wolf, CAMERAS[17], project_id=3)
    assert message is not None
    assert message.external_id == "17" and message.identity_type == "addaxai_camera_id"
    assert message.event_type == "detection"
    assert message.acquisition_channel == AcquisitionChannel.API
    assert message.ingestion_method == IngestionMethod.POLLING
    payload = message.payload
    assert payload["time"] == "2026-09-04T05:12:30+00:00"
    assert payload["lat"] == -24.8801 and payload["lon"] == 31.4907
    event = payload["events"][0]
    assert event["type"] == "SPECIES_DETECTION" and event["title"] == "Wolf at Waterhole north"
    assert event["lat"] == -24.8801
    context = event["context"]
    assert context["species"] == ["wolf"] and context["max_confidence"] == 0.94
    assert context["classifications"][0] == {
        "species": "wolf",
        "confidence": 0.94,
        "category": "animal",
    }
    assert context["image_uuid"] == wolf["uuid"] and context["camera_name"] == "Camera 17"
    assert context["link"] == "https://connect.example.org/projects/3/images?camera_id=17"
    assert payload["raw"] == wolf
    assert message.provider_metadata["image_uuid"] == wolf["uuid"]
    assert message.identity_attributes == {
        "camera_name": "Camera 17",
        "camera_device_id": "CT-0017",
        "site_name": "Waterhole north",
        "addaxai_project_id": 3,
    }
    person = parse_image(_source(), PAGE["items"][1], CAMERAS[17])
    assert (
        person is not None and person.payload["events"][0]["title"] == "Person at Waterhole north"
    )
    assert parse_image(_source(), PAGE["items"][2], CAMERAS[18]) is None
    no_camera = parse_image(_source(), PAGE["items"][2], None)
    assert no_camera is None
    assert parse_image(_source({"verified_only": True}), wolf, CAMERAS[17]) is None
    verified = parse_image(
        _source(),
        {**wolf, "is_verified": True, "observed_species": ["grey_wolf"], "detections": []},
        CAMERAS[17],
    )
    assert (
        verified is not None
        and verified.payload["events"][0]["title"] == "Grey wolf at Waterhole north"
    )
    with pytest.raises(ApplicationError):
        parse_image(_source(), {"uuid": "x"}, None)


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_poll_logs_in_and_moves_the_cursor(monkeypatch):
    calls = []
    logins = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/api/auth/login":
            logins.append(request.content.decode())
            return httpx.Response(
                200, json={"access_token": f"tok-{len(logins)}", "token_type": "bearer"}
            )
        if request.headers.get("authorization") != f"Bearer tok-{len(logins)}":
            return httpx.Response(401)
        if request.url.path == "/api/cameras":
            return httpx.Response(200, json=list(CAMERAS.values()))
        if request.url.path == "/api/images":
            start = request.url.params.get("start_date")
            items = [i for i in PAGE["items"] if i["captured_at"][:10] >= start]
            return httpx.Response(200, json={**PAGE, "items": items, "total": len(items)})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    store = MemoryCursorStore()
    connector = AddaxAiConnector(_source({"categories": ["animal", "person"]}, cursors=store))
    emitted = []

    async def emit(message):
        emitted.append(message)

    await connector.poll(emit)
    assert [m.payload["events"][0]["title"] for m in emitted] == [
        "Wolf at Waterhole north",
        "Person at Waterhole north",
    ]
    assert "username=bot%40example.org" in logins[0]
    image_call = next(c for c in calls if c[1] == "/api/images")
    assert image_call[2]["sort"] == "newest" and image_call[2]["limit"] == "100"
    state = store.state
    assert state["captured_after"] == "2026-09-04T05:12:30+00:00"
    assert state["seen"] == [PAGE["items"][0]["uuid"]]
    assert state["last_poll_emitted"] == 2 and state["last_rescan_at"]

    emitted.clear()
    await connector.poll(emit)
    assert emitted == []  # nothing newer than the cursor, no rescan due

    # a rescan is due: the overlap window is read again, the seen image at the cursor stays out
    store.state["last_rescan_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    await connector.poll(emit)
    assert [m.payload["events"][0]["title"] for m in emitted] == ["Person at Waterhole north"]

    # a reset from the API rescans from that instant
    emitted.clear()
    store.state = {"since": "2026-09-01T00:00:00+00:00", "reset_at": "x"}
    await connector.poll(emit)
    assert len(emitted) == 2 and "since" not in store.state
    await connector.client.close()


@pytest.mark.asyncio
async def test_login_failures_and_management(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            if "wrong" in request.content.decode():
                return httpx.Response(400, json={"detail": "LOGIN_BAD_CREDENTIALS"})
            return httpx.Response(200, json={"access_token": "t", "token_type": "bearer"})
        if request.url.path == "/api/cameras":
            return httpx.Response(200, json=list(CAMERAS.values()))
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    with pytest.raises(ApplicationError) as refused:
        await AddaxAiManagement(
            _source(credentials={"email": "x", "password": "wrong"})
        ).list_devices()
    assert refused.value.code == "CONNECTIVITY_AUTH_FAILED"
    with pytest.raises(ApplicationError):
        await AddaxAiManagement(_source(credentials={})).list_devices()
    devices = await AddaxAiManagement(_source()).list_devices()
    assert [d["external_id"] for d in devices] == ["17", "18"] and devices[0][
        "site"
    ] == "Waterhole north"
    assert (await AddaxAiManagement(_source()).test_connection())["cameras"] == 2


def test_adapter_metadata():
    adapter = AddaxAiConnectAdapter()
    assert adapter.polling and not adapter.push
    assert adapter.event_connector(_source()) is not None
    with pytest.raises(ApplicationError):
        adapter.parse_webhook(_source(), {"x": 1}, {})
    pushed = adapter.parse_webhook(_source(), {**PAGE["items"][0], "camera": CAMERAS[17]}, {})
    assert len(pushed) == 1
