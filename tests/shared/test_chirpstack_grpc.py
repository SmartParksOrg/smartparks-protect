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
    def __init__(self, channel):
        pass

    async def List(self, request, metadata=None, timeout=None):  # noqa: ASYNC109
        Recorder.calls.append(("ListApplications", request, metadata))
        return api.ListApplicationsResponse(
            total_count=1, result=[api.ApplicationListItem(id="a1", name="smartparks")]
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
        return "fake"


@pytest.fixture(autouse=True)
def fake_grpc(monkeypatch):
    Recorder.calls = []
    Recorder.fail = None
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
