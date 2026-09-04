"""The ChirpStack command connector against a mocked REST API."""

import base64
import json

import httpx
import pytest

from shared.connectivity.adapters.chirpstack import ChirpStackAdapter, ChirpStackCommands
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import ErrorCode
from shared.trace import ApplicationError
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


def _source() -> DataSourceContext:
    import uuid

    return DataSourceContext(
        id=uuid.uuid4(),
        name=unique_name("cs"),
        adapter_key="chirpstack",
        config={"mqtt_host": "x", "api_url": "http://chirpstack"},
        credentials={"api_token": "t0ken"},
        capabilities=AdapterCapabilities(downlink=True),
    )


def _patch(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_submit_queue_and_flush(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["queueItem"]["devEui"] == "70b3d57ed0001234"
            assert base64.b64decode(body["queueItem"]["data"]) == b"\xa4\x00"
            assert body["queueItem"]["fPort"] == 32 and body["queueItem"]["confirmed"] is False
            return httpx.Response(200, json={"id": "8d0c3b3e-1111-2222-3333-444444444444"})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "totalCount": 1,
                    "result": [
                        {
                            "id": "q1",
                            "fPort": 32,
                            "data": "pAA=",
                            "confirmed": False,
                            "isPending": False,
                            "fCntDown": 5,
                        }
                    ],
                },
            )
        return httpx.Response(200, json={})

    _patch(monkeypatch, handler)
    commands = ChirpStackCommands(_source())
    result = await commands.submit(
        "70B3D57ED0001234", b"\xa4\x00", {"f_port": 32, "confirmed": False}
    )
    assert result["provider_ref"] == "8d0c3b3e-1111-2222-3333-444444444444"
    assert result["statuses"] == ["accepted_by_network", "queued"]
    assert calls[0].headers["Grpc-Metadata-Authorization"] == "Bearer t0ken"
    assert calls[0].url.path == "/api/devices/70b3d57ed0001234/queue"
    queue = await commands.queue("70B3D57ED0001234")
    assert queue[0]["fCntDown"] == 5
    await commands.flush("70B3D57ED0001234")
    assert calls[-1].method == "DELETE"


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [
        (401, ErrorCode.CONNECTIVITY_AUTH_FAILED, False),
        (404, ErrorCode.DEVICE_NOT_FOUND, False),
        (400, ErrorCode.COMMAND_REJECTED, False),
        (503, ErrorCode.CONNECTIVITY_UNAVAILABLE, True),
    ],
)
async def test_submit_errors_are_structured(monkeypatch, status_code, code, retryable):
    _patch(monkeypatch, lambda request: httpx.Response(status_code, text="nope"))
    with pytest.raises(ApplicationError) as excinfo:
        await ChirpStackCommands(_source()).submit("aa", b"\x00", {"f_port": 1})
    assert excinfo.value.code == code and excinfo.value.retryable is retryable


def test_adapter_exposes_the_connector():
    assert isinstance(ChirpStackAdapter().command_connector(_source()), ChirpStackCommands)
