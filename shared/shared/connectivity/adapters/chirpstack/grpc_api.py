"""ChirpStack's native gRPC API (the `chirpstack-api` client, the same services the ChirpStack
UI uses) and, for installations behind a plain HTTP/1.1 reverse proxy, the same calls over
grpc-web, the protocol the ChirpStack web UI itself uses on the same paths (decision D131).
Answers are converted to the camelCase JSON shape the REST gateway returns, so the rest of the
adapter reads both alike.

`api_url` selects the transport by scheme: `grpcs://host:443` (TLS, for example through an
nginx `grpc_pass` location) or `grpc://host:8080` (plain, on a private network) for native
gRPC; `https://host` or `http://host` for grpc-web through whatever serves the web UI."""

import struct
from typing import Any
from urllib.parse import unquote, urlsplit

import grpc
import httpx
from chirpstack_api import api
from google.protobuf.json_format import MessageToDict

from shared.enums import ErrorCode
from shared.trace import ApplicationError

COMPONENT = "adapter.chirpstack"
CALL_TIMEOUT = 15.0
PAGE = 100
_AUTH_CODES = (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED)
_UNAVAILABLE_CODES = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
_STATUS_BY_NUMBER = {code.value[0]: code for code in grpc.StatusCode}


def is_grpc_url(url: str) -> bool:
    return urlsplit(url).scheme in ("grpc", "grpcs")


def is_web_url(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


def is_api_url(url: str) -> bool:
    """Native gRPC or grpc-web, by scheme."""
    return is_grpc_url(url) or is_web_url(url)


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


def _from_status(code: grpc.StatusCode, detail: str, what: str) -> ApplicationError:
    """The platform's error for a gRPC status, whichever transport carried it."""
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
                "or not reloaded in that nginx; an https:// api_url uses grpc-web through "
                "the web UI's own path instead"
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


def _translate(error: grpc.aio.AioRpcError, what: str) -> ApplicationError:
    code = error.code()
    return _from_status(code, error.details() or code.name, what)


def to_dict(message: Any) -> dict[str, Any]:
    result: dict[str, Any] = MessageToDict(message, preserving_proto_field_name=False)
    return result


def _encoding(name: str) -> int:
    """The enum value for `JSON` or `PROTOBUF`; anything else is JSON."""
    try:
        return int(api.Encoding.Value(name))
    except ValueError:
        return int(api.Encoding.JSON)


class _ChirpStackCalls:
    """The calls the adapter makes, on top of one unary invocation per transport."""

    async def _unary(
        self,
        service: str,
        method: str,
        request: Any,
        response_cls: Any,
        what: str,
        *,
        not_found_ok: bool = False,
    ) -> Any:
        raise NotImplementedError

    async def _pages(
        self, service: str, make_request: Any, response_cls: Any, what: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = await self._unary(
                service, "List", make_request(PAGE, offset), response_cls, what
            )
            page = [to_dict(item) for item in response.result]
            items.extend(page)
            offset += PAGE
            if offset >= int(response.total_count or 0) or not page:
                return items

    async def list_applications(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            "ApplicationService",
            lambda limit, offset: api.ListApplicationsRequest(
                tenant_id=tenant_id, limit=limit, offset=offset
            ),
            api.ListApplicationsResponse,
            "the tenant's applications",
        )

    async def list_devices(self, application_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            "DeviceService",
            lambda limit, offset: api.ListDevicesRequest(
                application_id=application_id, limit=limit, offset=offset
            ),
            api.ListDevicesResponse,
            f"application {application_id}",
        )

    async def list_tenants(self) -> list[dict[str, Any]]:
        """The tenants the key may list: a global key's tenants; a tenant key is refused
        (UNAUTHENTICATED), it cannot ask which tenant it belongs to."""
        return await self._pages(
            "TenantService",
            lambda limit, offset: api.ListTenantsRequest(limit=limit, offset=offset),
            api.ListTenantsResponse,
            "the tenants",
        )

    async def list_gateways(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            "GatewayService",
            lambda limit, offset: api.ListGatewaysRequest(
                tenant_id=tenant_id, limit=limit, offset=offset
            ),
            api.ListGatewaysResponse,
            "the tenant's gateways",
        )

    async def get_http_integration(self, application_id: str) -> dict[str, Any] | None:
        """The application's HTTP integration (`eventEndpointUrl` is a comma-separated list,
        `headers` a map), or None when the application has none."""
        response = await self._unary(
            "ApplicationService",
            "GetHttpIntegration",
            api.GetHttpIntegrationRequest(application_id=application_id),
            api.GetHttpIntegrationResponse,
            f"application {application_id}",
            not_found_ok=True,
        )
        return None if response is None else to_dict(response.integration)

    async def create_http_integration(
        self, application_id: str, event_endpoint_url: str, headers: dict[str, str]
    ) -> None:
        integration = api.HttpIntegration(
            application_id=application_id,
            headers=headers,
            encoding=api.Encoding.JSON,
            event_endpoint_url=event_endpoint_url,
        )
        await self._unary(
            "ApplicationService",
            "CreateHttpIntegration",
            api.CreateHttpIntegrationRequest(integration=integration),
            api.CreateHttpIntegrationRequest,
            f"application {application_id}",
        )

    async def update_http_integration(
        self,
        application_id: str,
        event_endpoint_url: str,
        headers: dict[str, str],
        encoding: str = "JSON",
    ) -> None:
        integration = api.HttpIntegration(
            application_id=application_id,
            headers=headers,
            encoding=_encoding(encoding),
            event_endpoint_url=event_endpoint_url,
        )
        await self._unary(
            "ApplicationService",
            "UpdateHttpIntegration",
            api.UpdateHttpIntegrationRequest(integration=integration),
            api.UpdateHttpIntegrationRequest,
            f"application {application_id}",
        )

    async def delete_http_integration(self, application_id: str) -> None:
        await self._unary(
            "ApplicationService",
            "DeleteHttpIntegration",
            api.DeleteHttpIntegrationRequest(application_id=application_id),
            api.DeleteHttpIntegrationRequest,
            f"application {application_id}",
        )

    async def enqueue(self, dev_eui: str, payload: bytes, f_port: int, confirmed: bool) -> str:
        request = api.EnqueueDeviceQueueItemRequest(
            queue_item=api.DeviceQueueItem(
                dev_eui=dev_eui, confirmed=confirmed, f_port=f_port, data=payload
            )
        )
        response = await self._unary(
            "DeviceService",
            "Enqueue",
            request,
            api.EnqueueDeviceQueueItemResponse,
            f"device {dev_eui}",
        )
        return str(response.id)

    async def queue(self, dev_eui: str) -> list[dict[str, Any]]:
        response = await self._unary(
            "DeviceService",
            "GetQueue",
            api.GetDeviceQueueItemsRequest(dev_eui=dev_eui),
            api.GetDeviceQueueItemsResponse,
            f"device {dev_eui}",
        )
        return [to_dict(item) for item in response.result]

    async def flush(self, dev_eui: str) -> None:
        await self._unary(
            "DeviceService",
            "FlushQueue",
            api.FlushDeviceQueueRequest(dev_eui=dev_eui),
            api.FlushDeviceQueueRequest,
            f"device {dev_eui}",
        )


class ChirpStackGrpc(_ChirpStackCalls):
    """Native gRPC over HTTP/2."""

    def __init__(self, url: str, token: str) -> None:
        self.target, self.tls = _target(url)
        self.metadata = (("authorization", f"Bearer {token}"),)

    def _channel(self) -> grpc.aio.Channel:
        if self.tls:
            return grpc.aio.secure_channel(self.target, grpc.ssl_channel_credentials())
        return grpc.aio.insecure_channel(self.target)

    async def _unary(
        self,
        service: str,
        method: str,
        request: Any,
        response_cls: Any,
        what: str,
        *,
        not_found_ok: bool = False,
    ) -> Any:
        stub_cls = getattr(api, f"{service}Stub")
        async with self._channel() as channel:
            call = getattr(stub_cls(channel), method)
            try:
                return await call(request, metadata=self.metadata, timeout=CALL_TIMEOUT)
            except grpc.aio.AioRpcError as error:
                if not_found_ok and error.code() == grpc.StatusCode.NOT_FOUND:
                    return None
                raise _translate(error, what) from error


class ChirpStackWeb(_ChirpStackCalls):
    """grpc-web over HTTP/1.1 (decision D131): one POST per unary call to `/api.<Service>/
    <Method>` with the protobuf message in a length-prefixed frame, the status in the
    `grpc-status` header or in the trailer frame. Works through any proxy that serves the
    ChirpStack web UI, which uses exactly this."""

    def __init__(self, url: str, token: str) -> None:
        parts = urlsplit(url)
        if not parts.hostname:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"api_url {url!r} has no host",
                component=COMPONENT,
                user_actionable=True,
            )
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.headers = {
            "content-type": "application/grpc-web+proto",
            "accept": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "authorization": f"Bearer {token}",
        }
        self.transport: httpx.AsyncBaseTransport | None = None  # tests inject one

    async def _unary(
        self,
        service: str,
        method: str,
        request: Any,
        response_cls: Any,
        what: str,
        *,
        not_found_ok: bool = False,
    ) -> Any:
        payload = request.SerializeToString()
        body = b"\x00" + struct.pack(">I", len(payload)) + payload
        try:
            async with httpx.AsyncClient(timeout=CALL_TIMEOUT, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base}/api.{service}/{method}", content=body, headers=self.headers
                )
        except httpx.HTTPError as error:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"ChirpStack API unreachable (grpc-web): {error}",
                component=COMPONENT,
                retryable=True,
            ) from error
        if response.status_code != 200:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=(
                    f"The server at api_url answered HTTP {response.status_code} instead of "
                    "grpc-web: is it the address of the ChirpStack web UI?"
                ),
                component=COMPONENT,
                user_actionable=True,
            )
        message, status, detail = _decode_web_frames(response)
        if status != 0:
            code = _STATUS_BY_NUMBER.get(status, grpc.StatusCode.UNKNOWN)
            if not_found_ok and code == grpc.StatusCode.NOT_FOUND:
                return None
            raise _from_status(code, detail or code.name, what)
        result = response_cls()
        if message is not None:
            result.ParseFromString(message)
        return result


def _decode_web_frames(response: httpx.Response) -> tuple[bytes | None, int, str]:
    """The message bytes, the gRPC status and its message from a grpc-web answer: data frames
    carry flag 0, the trailer frame flag 0x80 with `grpc-status` lines; an answer without a
    body carries the status in the headers."""
    data = response.content
    message: bytes | None = None
    status = int(response.headers.get("grpc-status", "0") or 0)
    detail = unquote(response.headers.get("grpc-message", "") or "")
    offset = 0
    while offset + 5 <= len(data):
        flag = data[offset]
        length = struct.unpack(">I", data[offset + 1 : offset + 5])[0]
        chunk = data[offset + 5 : offset + 5 + length]
        offset += 5 + length
        if flag & 0x80:
            for line in chunk.decode("utf-8", "replace").splitlines():
                key, _, value = line.partition(":")
                if key.strip().lower() == "grpc-status":
                    status = int(value.strip() or 0)
                elif key.strip().lower() == "grpc-message":
                    detail = unquote(value.strip())
        elif message is None:
            message = chunk
    return message, status, detail


def client_for(url: str, token: str) -> _ChirpStackCalls:
    """The transport `api_url` asks for: native gRPC for grpc(s)://, grpc-web for http(s)://."""
    return ChirpStackWeb(url, token) if is_web_url(url) else ChirpStackGrpc(url, token)
