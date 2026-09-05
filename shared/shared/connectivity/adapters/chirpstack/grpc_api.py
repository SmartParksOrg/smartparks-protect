"""ChirpStack's native gRPC API (the `chirpstack-api` client, the same services the ChirpStack
UI uses), for installations without the REST gateway. Answers are converted to the camelCase
JSON shape the REST gateway returns, so the rest of the adapter reads both alike.

`api_url` selects it by scheme: `grpcs://host:443` (TLS, for example through an nginx
`grpc_pass` location) or `grpc://host:8080` (plain, on a private network)."""

from typing import Any
from urllib.parse import urlsplit

import grpc
from chirpstack_api import api
from google.protobuf.json_format import MessageToDict

from shared.enums import ErrorCode
from shared.trace import ApplicationError

COMPONENT = "adapter.chirpstack"
CALL_TIMEOUT = 15.0
PAGE = 100
_AUTH_CODES = (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED)
_UNAVAILABLE_CODES = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)


def is_grpc_url(url: str) -> bool:
    return urlsplit(url).scheme in ("grpc", "grpcs")


def _target(url: str) -> tuple[str, bool]:
    parts = urlsplit(url)
    if not parts.hostname:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
            message=f"api_url {url!r} has no host",
            component=COMPONENT,
            user_actionable=True,
        )
    tls = parts.scheme == "grpcs"
    port = parts.port or (443 if tls else 8080)
    return f"{parts.hostname}:{port}", tls


def _translate(error: grpc.aio.AioRpcError, what: str) -> ApplicationError:
    code = error.code()
    detail = error.details() or code.name
    if code in _AUTH_CODES:
        return ApplicationError(
            code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
            message=f"ChirpStack API refused the token ({code.name}): {detail}",
            component=COMPONENT,
            user_actionable=True,
        )
    if code == grpc.StatusCode.NOT_FOUND:
        return ApplicationError(
            code=ErrorCode.DEVICE_NOT_FOUND,
            message=f"ChirpStack does not know {what}: {detail}",
            component=COMPONENT,
            user_actionable=True,
        )
    if code in _UNAVAILABLE_CODES:
        return ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=f"ChirpStack API unreachable ({code.name}): {detail}",
            component=COMPONENT,
            retryable=True,
        )
    if "http2 header with status" in detail:
        # A proxy in front of ChirpStack answered with a plain HTTP status instead of gRPC:
        # the request reached nginx but not a `grpc_pass` location (missing, in another
        # server block, or not reloaded), so ChirpStack received it over HTTP/1.1.
        status = detail.rsplit(" ", 1)[-1]
        return ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=(
                f"The proxy at api_url answered HTTP {status} instead of gRPC: the gRPC "
                "location (grpc_pass to ChirpStack's port 8080, matching /api.) is missing "
                "or not reloaded in that nginx"
            ),
            component=COMPONENT,
            user_actionable=True,
        )
    return ApplicationError(
        code=ErrorCode.COMMAND_REJECTED,
        message=f"ChirpStack rejected {what} ({code.name}): {detail}",
        component=COMPONENT,
        user_actionable=True,
    )


def to_dict(message: Any) -> dict[str, Any]:
    result: dict[str, Any] = MessageToDict(message, preserving_proto_field_name=False)
    return result


class ChirpStackGrpc:
    def __init__(self, url: str, token: str) -> None:
        self.target, self.tls = _target(url)
        self.metadata = (("authorization", f"Bearer {token}"),)

    def _channel(self) -> grpc.aio.Channel:
        if self.tls:
            return grpc.aio.secure_channel(self.target, grpc.ssl_channel_credentials())
        return grpc.aio.insecure_channel(self.target)

    async def _call(self, method: Any, request: Any, what: str) -> Any:
        try:
            return await method(request, metadata=self.metadata, timeout=CALL_TIMEOUT)
        except grpc.aio.AioRpcError as error:
            raise _translate(error, what) from error

    async def _pages(self, make_stub: Any, make_request: Any, what: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        async with self._channel() as channel:
            stub = make_stub(channel)
            while True:
                response = await self._call(stub.List, make_request(PAGE, offset), what)
                page = [to_dict(item) for item in response.result]
                items.extend(page)
                offset += PAGE
                if offset >= int(response.total_count or 0) or not page:
                    return items

    async def list_applications(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            api.ApplicationServiceStub,
            lambda limit, offset: api.ListApplicationsRequest(
                tenant_id=tenant_id, limit=limit, offset=offset
            ),
            "the tenant's applications",
        )

    async def list_devices(self, application_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            api.DeviceServiceStub,
            lambda limit, offset: api.ListDevicesRequest(
                application_id=application_id, limit=limit, offset=offset
            ),
            f"application {application_id}",
        )

    async def list_gateways(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            api.GatewayServiceStub,
            lambda limit, offset: api.ListGatewaysRequest(
                tenant_id=tenant_id, limit=limit, offset=offset
            ),
            "the tenant's gateways",
        )

    async def enqueue(self, dev_eui: str, payload: bytes, f_port: int, confirmed: bool) -> str:
        request = api.EnqueueDeviceQueueItemRequest(
            queue_item=api.DeviceQueueItem(
                dev_eui=dev_eui, confirmed=confirmed, f_port=f_port, data=payload
            )
        )
        async with self._channel() as channel:
            response = await self._call(
                api.DeviceServiceStub(channel).Enqueue, request, f"device {dev_eui}"
            )
        return str(response.id)

    async def queue(self, dev_eui: str) -> list[dict[str, Any]]:
        async with self._channel() as channel:
            response = await self._call(
                api.DeviceServiceStub(channel).GetQueue,
                api.GetDeviceQueueItemsRequest(dev_eui=dev_eui),
                f"device {dev_eui}",
            )
        return [to_dict(item) for item in response.result]

    async def flush(self, dev_eui: str) -> None:
        async with self._channel() as channel:
            await self._call(
                api.DeviceServiceStub(channel).FlushQueue,
                api.FlushDeviceQueueRequest(dev_eui=dev_eui),
                f"device {dev_eui}",
            )
