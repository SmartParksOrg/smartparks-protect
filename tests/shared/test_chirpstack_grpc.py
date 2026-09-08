"""ChirpStack over gRPC: the URL scheme selects it, answers take the REST shape, and errors
become the platform's error codes."""

import uuid
from typing import ClassVar

import grpc
import pytest
from chirpstack_api import api

from shared.connectivity.adapters import chirpstack
from shared.connectivity.adapters.chirpstack import (
    ChirpStackCommands,
    ChirpStackManagement,
    grpc_api,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import ErrorCode
from shared.trace import ApplicationError

pytestmark = pytest.mark.asyncio


def source(url: str) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="cs",
        adapter_key="chirpstack",
        config={"api_url": url, "tenant_id": "t1"},
        credentials={"api_token": "key"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


class FakeChannel:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Recorder:
    calls: ClassVar[list[tuple[str, object, object]]] = []
    fail: ClassVar[grpc.StatusCode | None] = None
    fail_detail: ClassVar[str | None] = None


class FakeDeviceService:
    def __init__(self, channel):
        pass

    async def Enqueue(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("Enqueue", request, metadata))
        if Recorder.fail:
            raise FakeRpcError(Recorder.fail)
        return api.EnqueueDeviceQueueItemResponse(id="q-1")

    async def GetQueue(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        return api.GetDeviceQueueItemsResponse(
            total_count=1,
            result=[api.DeviceQueueItem(id="q-1", dev_eui=request.dev_eui, f_port=4, data=b"\x01")],
        )

    async def FlushQueue(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("FlushQueue", request, metadata))
        return api.FlushDeviceQueueRequest()

    async def List(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        return api.ListDevicesResponse(
            total_count=1,
            result=[
                api.DeviceListItem(
                    dev_eui="0016c001f01192a0",
                    name="SP051307",
                    device_profile_name="opencollar_edge_v6",
                )
            ],
        )


class FakeApplicationService:
    # the HTTP integration per application: None means the application has none
    integrations: ClassVar[dict[str, api.HttpIntegration | None]] = {}
    applications: ClassVar[list[tuple[str, str]]] = [("a1", "smartparks")]

    def __init__(self, channel):
        pass

    async def List(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("ListApplications", request, metadata))
        return api.ListApplicationsResponse(
            total_count=len(self.applications),
            result=[api.ApplicationListItem(id=i, name=n) for i, n in self.applications],
        )

    async def GetHttpIntegration(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        current = self.integrations.get(request.application_id)
        if current is None:
            raise FakeRpcError(grpc.StatusCode.NOT_FOUND)
        return api.GetHttpIntegrationResponse(integration=current)

    async def CreateHttpIntegration(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("CreateHttpIntegration", request, metadata))
        if Recorder.fail:
            raise FakeRpcError(Recorder.fail)
        self.integrations[request.integration.application_id] = request.integration
        return api.CreateHttpIntegrationRequest()

    async def UpdateHttpIntegration(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("UpdateHttpIntegration", request, metadata))
        self.integrations[request.integration.application_id] = request.integration
        return api.UpdateHttpIntegrationRequest()


class FakeGatewayService:
    def __init__(self, channel):
        pass

    async def List(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        item = api.GatewayListItem(
            gateway_id="1dee013a9b72a568", name="Utrecht", state=api.GatewayState.ONLINE
        )
        item.location.latitude = 52.11
        item.location.longitude = 5.13
        return api.ListGatewaysResponse(total_count=1, result=[item])


class FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code):
        self._fake_code = code

    def code(self):
        return self._fake_code

    def details(self):
        return Recorder.fail_detail or "fake"


@pytest.fixture(autouse=True)
def fake_grpc(monkeypatch):
    Recorder.calls = []
    Recorder.fail = None
    FakeApplicationService.integrations = {}
    FakeApplicationService.applications = [("a1", "smartparks")]
    monkeypatch.setattr(grpc_api.api, "DeviceServiceStub", FakeDeviceService)
    monkeypatch.setattr(grpc_api.api, "ApplicationServiceStub", FakeApplicationService)
    monkeypatch.setattr(grpc_api.api, "GatewayServiceStub", FakeGatewayService)
    monkeypatch.setattr(grpc_api.ChirpStackGrpc, "_channel", lambda self: FakeChannel())


def test_scheme_selects_grpc_and_target():
    assert grpc_api.is_grpc_url("grpcs://cs.example:443") and not grpc_api.is_grpc_url(
        "https://cs.example/rest"
    )
    assert grpc_api._target("grpcs://cs.example") == ("cs.example:443", True)
    assert grpc_api._target("grpc://10.0.0.5:8080") == ("10.0.0.5:8080", False)
    with pytest.raises(ApplicationError) as excinfo:  # ChirpStack v4 speaks gRPC only
        _ = ChirpStackManagement(source("https://cs.example/rest")).grpc
    assert "gRPC" in excinfo.value.message
    assert ChirpStackManagement(source("grpcs://cs.example")).grpc is not None


async def test_management_and_commands_over_grpc():
    management = ChirpStackManagement(source("grpcs://cs.example:443"))
    apps = await management.list_applications()
    assert apps == [{"id": "a1", "name": "smartparks"}]
    assert Recorder.calls[0][2] == (("authorization", "Bearer key"),)
    devices = await management.list_devices()
    assert devices[0]["external_id"] == "0016C001F01192A0" and devices[0]["name"] == "SP051307"
    updates = await management.list_gateway_updates()
    assert updates[0].gateway_id == "1dee013a9b72a568" and updates[0].latitude == pytest.approx(
        52.11
    )
    assert updates[0].status == "online"
    check = await management.test_connection()
    assert check["ok"] is True and check["applications"] == 1

    commands = ChirpStackCommands(source("grpcs://cs.example:443"))
    result = await commands.submit(
        "0016C001F01192A0", b"\xa4\x00", {"f_port": 32, "confirmed": True}
    )
    assert result["provider_ref"] == "q-1" and result["statuses"] == [
        "accepted_by_network",
        "queued",
    ]
    request = Recorder.calls[-1][1]
    assert request.queue_item.dev_eui == "0016c001f01192a0" and request.queue_item.f_port == 32
    assert request.queue_item.confirmed is True and request.queue_item.data == b"\xa4\x00"
    queue = await commands.queue("0016C001F01192A0")
    assert queue[0]["fPort"] == 4 and queue[0]["devEui"] == "0016c001f01192a0"
    await commands.flush("0016C001F01192A0")
    assert Recorder.calls[-1][0] == "FlushQueue"


async def test_grpc_errors_become_platform_errors():
    commands = ChirpStackCommands(source("grpc://cs.example:8080"))
    for code, expected in (
        (grpc.StatusCode.UNAUTHENTICATED, ErrorCode.CONNECTIVITY_AUTH_FAILED),
        (grpc.StatusCode.NOT_FOUND, ErrorCode.DEVICE_NOT_FOUND),
        (grpc.StatusCode.UNAVAILABLE, ErrorCode.CONNECTIVITY_UNAVAILABLE),
        (grpc.StatusCode.INVALID_ARGUMENT, ErrorCode.COMMAND_REJECTED),
    ):
        Recorder.fail = code
        with pytest.raises(ApplicationError) as excinfo:
            await commands.submit("0016C001F01192A0", b"\x00", {"f_port": 1})
        assert excinfo.value.code == expected
    assert chirpstack.ChirpStackAdapter.config_example["api_url"].startswith("grpcs://")


async def test_proxy_without_grpc_location_is_explained():
    """nginx without a `grpc_pass` location hands the call to ChirpStack over HTTP/1.1,
    which answers an empty 400; grpc reports that as INTERNAL with the HTTP status."""
    commands = ChirpStackCommands(source("grpcs://cs.example:443"))
    Recorder.fail = grpc.StatusCode.INTERNAL
    Recorder.fail_detail = "Received http2 header with status: 400"
    try:
        with pytest.raises(ApplicationError) as excinfo:
            await commands.submit("0016C001F01192A0", b"\x00", {"f_port": 1})
    finally:
        Recorder.fail_detail = None
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_UNAVAILABLE
    assert "HTTP 400" in excinfo.value.message and "grpc_pass" in excinfo.value.message


async def test_connect_applications_creates_merges_and_keeps_headers():
    """Decision D125: no integration becomes one with our URL; an existing one keeps its URLs
    and headers and gains ours; a rotated token replaces our old entry; the rest is untouched."""
    FakeApplicationService.applications = [("a1", "smartparks"), ("a2", "trackers"), ("a3", "done")]
    FakeApplicationService.integrations = {
        "a2": api.HttpIntegration(
            application_id="a2",
            headers={"Authorization": "Bearer theirs"},
            encoding=api.Encoding.PROTOBUF,
            event_endpoint_url="https://other.example/hook, https://protect.example/api/v1/ingest/http/S?token=old",
        ),
        "a3": api.HttpIntegration(
            application_id="a3",
            event_endpoint_url="https://protect.example/api/v1/ingest/http/S?token=new",
        ),
    }
    url = "https://protect.example/api/v1/ingest/http/S?token=new"
    management = ChirpStackManagement(source("grpc://cs:8080"))
    results = await management.connect_applications(url)
    assert [(r["name"], r["outcome"]) for r in results] == [
        ("smartparks", "connected"),
        ("trackers", "updated"),
        ("done", "already"),
    ]
    created = FakeApplicationService.integrations["a1"]
    assert created.event_endpoint_url == url and created.encoding == api.Encoding.JSON
    updated = FakeApplicationService.integrations["a2"]
    assert updated.event_endpoint_url == f"https://other.example/hook,{url}"
    assert dict(updated.headers) == {"Authorization": "Bearer theirs"}
    assert updated.encoding == api.Encoding.PROTOBUF
    assert [c[0] for c in Recorder.calls if "Integration" in c[0]] == [
        "CreateHttpIntegration",
        "UpdateHttpIntegration",
    ]

    status = await management.integration_status("https://protect.example/api/v1/ingest/http/S")
    assert [(a["name"], a["state"]) for a in status] == [
        ("smartparks", "connected"),
        ("trackers", "connected"),
        ("done", "connected"),
    ]
    FakeApplicationService.integrations["a2"].event_endpoint_url = "https://other.example/hook"
    del FakeApplicationService.integrations["a1"]
    status = await management.integration_status("https://protect.example/api/v1/ingest/http/S")
    assert [(a["name"], a["state"]) for a in status] == [
        ("smartparks", "none"),
        ("trackers", "other"),
        ("done", "connected"),
    ]


async def test_connect_applications_reports_a_refused_application():
    FakeApplicationService.applications = [("a1", "smartparks")]
    management = ChirpStackManagement(source("grpc://cs:8080"))
    Recorder.fail = grpc.StatusCode.PERMISSION_DENIED
    results = await management.connect_applications("https://protect.example/hook?token=t")
    assert results[0]["outcome"] == "failed" and "refused" in results[0]["error"]
