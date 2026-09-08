"""ChirpStack over gRPC: the URL scheme selects it, answers take the REST shape, and errors
become the platform's error codes."""

import struct
import uuid
from typing import ClassVar

import grpc
import httpx
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


class FakeTenantService:
    tenants: ClassVar[list[tuple[str, str]]] = [("t1", "Smart Parks")]
    fail: ClassVar[grpc.StatusCode | None] = None

    def __init__(self, channel):
        pass

    async def List(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        if self.fail:
            raise FakeRpcError(self.fail)
        return api.ListTenantsResponse(
            total_count=len(self.tenants),
            result=[api.TenantListItem(id=i, name=n) for i, n in self.tenants],
        )


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
    monkeypatch.setattr(grpc_api.api, "TenantServiceStub", FakeTenantService)
    FakeTenantService.tenants = [("t1", "Smart Parks")]
    FakeTenantService.fail = None
    monkeypatch.setattr(grpc_api.ChirpStackGrpc, "_channel", lambda self: FakeChannel())


def test_scheme_selects_grpc_and_target():
    assert grpc_api.is_grpc_url("grpcs://cs.example:443") and not grpc_api.is_grpc_url(
        "https://cs.example/rest"
    )
    assert grpc_api._target("grpcs://cs.example") == ("cs.example:443", True)
    assert grpc_api._target("grpc://10.0.0.5:8080") == ("10.0.0.5:8080", False)
    # https:// is grpc-web, the web UI's own transport (decision D131); a bare scheme is refused
    assert isinstance(
        ChirpStackManagement(source("https://cs.example")).grpc, grpc_api.ChirpStackWeb
    )
    assert isinstance(
        ChirpStackManagement(source("grpcs://cs.example")).grpc, grpc_api.ChirpStackGrpc
    )
    with pytest.raises(ApplicationError) as excinfo:
        _ = ChirpStackManagement(source("ftp://cs.example")).grpc
    assert "grpc-web" in excinfo.value.message


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
    assert chirpstack.ChirpStackAdapter.quick_setup["credential_key"] == "api_token"


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
    # a dry run reports the same outcomes and writes nothing (decision D129)
    preview = await management.connect_applications(url, dry_run=True)
    assert [(r["name"], r["outcome"]) for r in preview] == [
        ("smartparks", "connected"),
        ("trackers", "updated"),
        ("done", "already"),
    ]
    assert preview[1]["before"] == [
        "https://other.example/hook",
        "https://protect.example/api/v1/ingest/http/S?token=old",
    ]
    assert preview[1]["headers"] == ["Authorization"]
    assert "a1" not in FakeApplicationService.integrations
    assert not [c for c in Recorder.calls if "Integration" in c[0]]
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


async def test_quick_setup_reads_the_tenant_from_the_address_and_defaults_to_grpc_web(monkeypatch):
    """Decision D128 with D131: the address copied from the browser tab gives the origin and
    the tenant; the API address defaults to the origin (grpc-web); the key is asked only when
    the tenant is still missing, and a tenant key cannot answer."""
    from dataclasses import replace

    # the lookups go through the native fakes whatever the scheme
    monkeypatch.setattr(
        chirpstack,
        "client_for",
        lambda url, token: grpc_api.ChirpStackGrpc("grpc://cs:8080", token),
    )
    adapter = chirpstack.ChirpStackAdapter()
    base = source("")
    tenant = "8e0ba51b-cf1a-4f0d-b955-faa9bc030df7"
    context = replace(
        base, config={"web_url": f"https://cs.example.org/#/tenants/{tenant}/applications"}
    )
    completed = await adapter.complete_config(context)
    assert completed["web_url"] == "https://cs.example.org"
    assert completed["api_url"] == "https://cs.example.org"
    assert completed["tenant_id"] == tenant
    assert Recorder.calls == []  # nothing asked of the key
    # no tenant in the address: a global key with one tenant answers
    context = replace(base, config={"web_url": "https://cs.example.org/"})
    assert (await adapter.complete_config(context))["tenant_id"] == "t1"
    # the example address the old form left behind counts as unset
    context = replace(
        base,
        config={
            "web_url": "https://cs.example.org",
            "api_url": "grpcs://chirpstack.example.org:443",
            "tenant_id": "given",
        },
    )
    assert (await adapter.complete_config(context))["api_url"] == "https://cs.example.org"
    # a native address set by hand stays
    context = replace(
        base,
        config={
            "web_url": "https://cs.example.org",
            "api_url": "grpcs://cs.example.org:443",
            "tenant_id": "given",
        },
    )
    assert (await adapter.complete_config(context))["api_url"] == "grpcs://cs.example.org:443"
    # a tenant key is refused when it asks for its tenants: the sentence says what to do
    context = replace(base, config={"web_url": "https://cs.example.org"})
    FakeTenantService.fail = grpc.StatusCode.UNAUTHENTICATED
    with pytest.raises(ApplicationError, match="copy the address from the browser"):
        await adapter.complete_config(context)
    FakeTenantService.fail = None
    FakeTenantService.tenants = [("t1", "One"), ("t2", "Two")]
    with pytest.raises(ApplicationError, match="2 tenants"):
        await adapter.complete_config(context)
    FakeTenantService.tenants = []
    with pytest.raises(ApplicationError, match="no tenant"):
        await adapter.complete_config(context)
    # no key: nothing looked up, the addresses still derived
    context = replace(context, credentials={})
    assert (await adapter.complete_config(context))["api_url"] == "https://cs.example.org"


def _web_frame(message: bytes, flag: int = 0) -> bytes:
    return bytes([flag]) + struct.pack(">I", len(message)) + message


async def test_grpc_web_transport_frames_status_and_errors():
    """Decision D131: a unary call over grpc-web is one POST with a length-prefixed frame; the
    status comes from the header or the trailer frame; errors map like native ones."""
    seen: list[httpx.Request] = []
    answers: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers[request.url.path]

    client = grpc_api.ChirpStackWeb("https://cs.example.org/#/tenants/x", "key")
    client.transport = httpx.MockTransport(handler)
    listing = api.ListApplicationsResponse(
        total_count=1, result=[api.ApplicationListItem(id="a1", name="smartparks")]
    ).SerializeToString()
    answers["/api.ApplicationService/List"] = httpx.Response(
        200,
        content=_web_frame(listing) + _web_frame(b"grpc-status: 0\r\ngrpc-message: \r\n", 0x80),
        headers={"content-type": "application/grpc-web+proto"},
    )
    assert await client.list_applications("t1") == [{"id": "a1", "name": "smartparks"}]
    request = seen[-1]
    assert request.url == "https://cs.example.org/api.ApplicationService/List"
    assert request.headers["authorization"] == "Bearer key"
    assert request.headers["content-type"] == "application/grpc-web+proto"
    body = request.content
    assert body[0] == 0 and struct.unpack(">I", body[1:5])[0] == len(body) - 5
    sent = api.ListApplicationsRequest()
    sent.ParseFromString(body[5:])
    assert sent.tenant_id == "t1" and sent.limit == grpc_api.PAGE

    # not found in the trailer frame: None for the integration lookup
    answers["/api.ApplicationService/GetHttpIntegration"] = httpx.Response(
        200, content=_web_frame(b"grpc-status: 5\r\ngrpc-message: not%20found\r\n", 0x80)
    )
    assert await client.get_http_integration("a1") is None
    # unauthenticated in the headers, no body
    answers["/api.TenantService/List"] = httpx.Response(
        200, headers={"grpc-status": "16", "grpc-message": "bad%20token"}
    )
    with pytest.raises(ApplicationError) as refused:
        await client.list_tenants()
    assert (
        refused.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
        and "bad token" in refused.value.message
    )
    # a proxy answering plain HTTP
    answers["/api.GatewayService/List"] = httpx.Response(502, content=b"bad gateway")
    with pytest.raises(ApplicationError) as down:
        await client.list_gateways("t1")
    assert (
        down.value.code == ErrorCode.CONNECTIVITY_UNAVAILABLE and "HTTP 502" in down.value.message
    )
