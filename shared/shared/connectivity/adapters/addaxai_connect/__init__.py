"""AddaxAI Connect inbound connector (architecture 18.3, decisions D16, D63 and D64).

Camera trap detections from AddaxAI Connect enter the same pipeline as device data: every
classified image with a detection becomes a source event on the camera's identity and a
`SPECIES_DETECTION` event with the species, confidence, category, camera and site, the
camera's location and a link back.

Built from the AddaxAI Connect API (services/api/routers/images.py, cameras.py, auth):

- `POST /api/auth/login` (form `username`, `password`) answers `{"access_token", ...}`; the
  JWT lives one hour, so the connector logs in again on 401 or after 50 minutes (D63).
- `GET /api/cameras?project_id=` lists cameras with `id`, `name`, `device_id`, `location`
  (`{lat, lon}` from the latest report), `current_site` (`{id, name}`) and `project_id`.
- `GET /api/images` is paginated (`page`, `limit` up to 100) and filters on `start_date`,
  `project_id`, `min_classification_confidence`, `sort=newest`; items carry `uuid`,
  `camera_id`, `camera_name`, `site_name`, `captured_at`, `top_species`, `max_confidence`,
  `is_verified`, `observed_species` and `detections[].classifications[]`.

The cursor (D64) is the newest `captured_at` seen plus the uuids at that instant. A rescan
over `overlap_days` runs every `rescan_interval_hours`; the data source's "rescan from" action
resets the cursor for older bulk imports. Duplicate images are dropped by the pipeline's
canonical keys either way.

Config: `url`, `web_url` (default url), `project_ids` (AddaxAI Connect project ids, empty
for every project the account sees), `poll_interval_seconds` (300), `overlap_days` (7),
`rescan_interval_hours` (24), `min_confidence` (0.5), `species` (list, empty for all),
`categories` (animal, person, vehicle; empty for all), `verified_only` (false).
Credentials: `email`, `password`. Deep link paths are a guess until seen live.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    CursorStore,
    DataSourceContext,
    Emit,
    EventConnector,
    InboundMessage,
    MemoryCursorStore,
)
from shared.connectivity.transports.polling import PollingConnector
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.addaxai_connect")

IDENTITY_TYPE = "addaxai_camera_id"
EVENT_TYPE = "SPECIES_DETECTION"
PAGE_SIZE = 100
MAX_PAGES = 200
TOKEN_LIFETIME = timedelta(minutes=50)
HTTP_TIMEOUT = 30.0
DEFAULTS: dict[str, Any] = {
    "poll_interval_seconds": 300,
    "overlap_days": 7,
    "rescan_interval_hours": 24,
    "min_confidence": 0.5,
    "verified_only": False,
}


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.addaxai_connect", user_actionable=True
    )


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def setting(source: DataSourceContext, key: str) -> Any:
    value = source.config.get(key)
    return DEFAULTS.get(key) if value in (None, "") else value


def base_url(source: DataSourceContext) -> str:
    url = str(source.config.get("url") or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise _error(
            "the AddaxAI Connect source needs `url` in config (http or https)",
            ErrorCode.CONNECTIVITY_AUTH_FAILED,
        )
    return url


def detections_of(image: dict[str, Any], source: DataSourceContext) -> list[dict[str, Any]]:
    """Detections above the threshold that pass the category and species filters."""
    minimum = float(setting(source, "min_confidence") or 0)
    categories = {str(c).lower() for c in source.config.get("categories") or []}
    species_filter = {str(s).lower() for s in source.config.get("species") or []}
    result = []
    for detection in image.get("detections") or []:
        if not isinstance(detection, dict):
            continue
        category = str(detection.get("category") or "").lower()
        if categories and category not in categories:
            continue
        given = [c for c in detection.get("classifications") or [] if isinstance(c, dict)]
        classifications = [c for c in given if float(c.get("confidence") or 0) >= minimum]
        if given and not classifications:
            continue  # a species was suggested, but not confidently enough
        if not given and float(detection.get("confidence") or 0) < minimum:
            continue
        if species_filter:
            classifications = [
                c for c in classifications if str(c.get("species") or "").lower() in species_filter
            ]
            if not classifications:
                continue
        result.append({**detection, "classifications": classifications})
    return result


def parse_image(
    source: DataSourceContext,
    image: dict[str, Any],
    camera: dict[str, Any] | None,
    *,
    project_id: int | None = None,
) -> InboundMessage | None:
    """One classified image to a message, or None when nothing passes the filters."""
    if not isinstance(image, dict) or image.get("camera_id") is None or not image.get("uuid"):
        raise _error("AddaxAI Connect image without camera_id or uuid")
    if bool(setting(source, "verified_only")) and not image.get("is_verified"):
        return None
    detections = detections_of(image, source)
    observed = [str(s) for s in image.get("observed_species") or []]
    if not detections and not (image.get("is_verified") and observed):
        return None
    captured = _time(image.get("captured_at"))
    species: list[dict[str, Any]] = []
    for detection in detections:
        for classification in detection.get("classifications") or []:
            species.append(
                {
                    "species": classification.get("species"),
                    "confidence": classification.get("confidence"),
                    "category": detection.get("category"),
                }
            )
        if not detection.get("classifications"):
            species.append(
                {
                    "species": detection.get("category"),
                    "confidence": detection.get("confidence"),
                    "category": detection.get("category"),
                }
            )
    names = observed or [str(s["species"]) for s in species if s.get("species")]
    unique_names = list(dict.fromkeys(n for n in names if n))
    camera_name = str(image.get("camera_name") or (camera or {}).get("name") or image["camera_id"])
    site_name = image.get("site_name") or ((camera or {}).get("current_site") or {}).get("name")
    where = site_name or camera_name
    label = ", ".join(n.replace("_", " ").capitalize() for n in unique_names) or "Detection"
    location = (camera or {}).get("location") or {}
    latitude = location.get("lat") if isinstance(location, dict) else None
    longitude = location.get("lon") if isinstance(location, dict) else None
    if (camera or {}).get("project_id") is not None:
        project_id = int((camera or {})["project_id"])
    web_url = str(source.config.get("web_url") or source.config.get("url") or "").rstrip("/")
    link = (
        f"{web_url}/projects/{project_id}/images?camera_id={image['camera_id']}"
        if web_url and project_id is not None
        else None
    )
    event = {
        "type": EVENT_TYPE,
        "title": f"{label} at {where}",
        "severity": "info",
        "context": {
            "species": unique_names,
            "top_species": image.get("top_species"),
            "max_confidence": image.get("max_confidence"),
            "classifications": species,
            "categories": sorted({str(d.get("category")) for d in detections if d.get("category")}),
            "detection_count": len(detections),
            "verified": bool(image.get("is_verified")),
            "camera_id": image["camera_id"],
            "camera_name": camera_name,
            "site_name": site_name,
            "image_uuid": image["uuid"],
            "link": link,
        },
    }
    if latitude is not None and longitude is not None:
        event["lat"], event["lon"] = latitude, longitude
    payload: dict[str, Any] = {
        "time": captured.isoformat() if captured else None,
        "events": [event],
        "raw": image,
    }
    if latitude is not None and longitude is not None:
        payload["lat"], payload["lon"] = latitude, longitude
    identity_attributes = {
        k: v
        for k, v in {
            "camera_name": camera_name,
            "camera_device_id": (camera or {}).get("device_id"),
            "site_name": site_name,
            "addaxai_project_id": project_id,
        }.items()
        if v not in (None, "")
    }
    return InboundMessage(
        external_id=str(image["camera_id"]),
        event_type="detection",
        payload={k: v for k, v in payload.items() if v is not None},
        acquisition_channel=AcquisitionChannel.API,
        ingestion_method=IngestionMethod.POLLING,
        provider_metadata={
            "image_uuid": image["uuid"],
            "captured_at": image.get("captured_at"),
            "status": image.get("status"),
        },
        network_received_at=None,
        identity_type=IDENTITY_TYPE,
        identity_attributes=identity_attributes,
    )


class AddaxAiClient:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = base_url(source)
        self.client = httpx.AsyncClient(base_url=self.base, timeout=HTTP_TIMEOUT)
        self.token: str | None = None
        self.token_at: datetime | None = None

    async def login(self) -> str:
        email, password = (
            self.source.credentials.get("email"),
            self.source.credentials.get("password"),
        )
        if not email or not password:
            raise _error(
                "the AddaxAI Connect source needs `email` and `password` in credentials",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        response = await self.client.post(
            "/api/auth/login", data={"username": email, "password": password}
        )
        if response.status_code in (400, 401, 403):
            raise _error(
                f"AddaxAI Connect refused the credentials ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        response.raise_for_status()
        token = str(response.json().get("access_token") or "")
        if not token:
            raise _error(
                "AddaxAI Connect login answered without a token", ErrorCode.CONNECTIVITY_AUTH_FAILED
            )
        self.token, self.token_at = token, datetime.now(UTC)
        return token

    async def _headers(self) -> dict[str, str]:
        if (
            self.token is None
            or self.token_at is None
            or datetime.now(UTC) - self.token_at > TOKEN_LIFETIME
        ):
            await self.login()
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        response = await self.client.get(path, params=clean, headers=await self._headers())
        if response.status_code == 401:
            await self.login()
            response = await self.client.get(path, params=clean, headers=await self._headers())
        if response.status_code in (401, 403):
            raise _error(
                f"AddaxAI Connect refused the request ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        response.raise_for_status()
        return response.json()

    async def cameras(self, project_id: int | None) -> dict[int, dict[str, Any]]:
        body = await self.get("/api/cameras", project_id=project_id)
        return {int(c["id"]): c for c in body if isinstance(c, dict) and c.get("id") is not None}

    async def images(self, page: int, start_date: str, project_id: int | None) -> dict[str, Any]:
        body = await self.get(
            "/api/images",
            page=page,
            limit=PAGE_SIZE,
            sort="newest",
            start_date=start_date,
            project_id=project_id,
            show_empty="false",
        )
        return body if isinstance(body, dict) else {"items": [], "pages": 0}

    async def close(self) -> None:
        await self.client.aclose()


class AddaxAiConnector(PollingConnector):
    def __init__(self, source: DataSourceContext) -> None:
        super().__init__(float(setting(source, "poll_interval_seconds")))
        self.source = source
        self.cursors: CursorStore = source.cursors or MemoryCursorStore()
        self.client: AddaxAiClient | None = None

    def _client(self) -> AddaxAiClient:
        if self.client is None:
            self.client = AddaxAiClient(self.source)
        return self.client

    async def poll(self, emit: Emit) -> None:
        state = await self.cursors.load()
        now = datetime.now(UTC)
        overlap = timedelta(days=float(setting(self.source, "overlap_days")))
        reset = "since" in state
        newest = _time(state.get("since")) if reset else _time(state.get("captured_after"))
        seen = set() if reset else {str(u) for u in state.get("seen") or []}
        last_rescan = _time(state.get("last_rescan_at"))
        rescan_due = not reset and (
            newest is None
            or last_rescan is None
            or now - last_rescan
            >= timedelta(hours=float(setting(self.source, "rescan_interval_hours")))
        )
        start = (newest - overlap) if (newest and rescan_due) else newest
        if start is None:
            start = now - overlap
        project_ids: list[int | None] = [
            int(p) for p in self.source.config.get("project_ids") or []
        ] or [None]
        client = self._client()
        emitted = 0
        newest_seen = newest
        new_seen: set[str] = set(seen)
        for project_id in project_ids:
            cameras = await client.cameras(project_id)
            page = 1
            while page <= MAX_PAGES:
                body = await client.images(page, start.date().isoformat(), project_id)
                items = body.get("items") or []
                stop = False
                for image in items:
                    captured = _time(image.get("captured_at"))
                    if captured is not None and captured < start:
                        stop = True
                        break
                    uuid_ = str(image.get("uuid") or "")
                    already = (
                        newest is not None
                        and captured is not None
                        and (captured < newest or (captured == newest and uuid_ in seen))
                    )
                    if already and (not rescan_due or (captured == newest and uuid_ in seen)):
                        continue
                    try:
                        message = parse_image(
                            self.source,
                            image,
                            cameras.get(int(image.get("camera_id", -1))),
                            project_id=project_id,
                        )
                    except (ApplicationError, ValueError, TypeError) as error:
                        log.warning(
                            "addaxai image dropped", source=self.source.name, error=str(error)
                        )
                        continue
                    if message is not None:
                        await emit(message)
                        emitted += 1
                    if captured is not None:
                        if newest_seen is None or captured > newest_seen:
                            newest_seen, new_seen = captured, {uuid_}
                        elif captured == newest_seen:
                            new_seen.add(uuid_)
                if stop or not items or page >= int(body.get("pages") or page):
                    break
                page += 1
        await self.cursors.save(
            {
                "captured_after": newest_seen.isoformat() if newest_seen else None,
                "seen": sorted(new_seen)[:500],
                "last_rescan_at": (
                    now.isoformat() if (rescan_due or reset) else state.get("last_rescan_at")
                ),
                "last_poll_at": now.isoformat(),
                "last_poll_emitted": emitted,
            }
        )
        if emitted:
            log.info("addaxai poll", source=self.source.name, emitted=emitted)

    async def run(self, emit: Emit) -> None:
        try:
            await super().run(emit)
        finally:
            if self.client is not None:
                await self.client.close()


class AddaxAiManagement:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def list_devices(self) -> list[dict[str, Any]]:
        client = AddaxAiClient(self.source)
        try:
            project_ids: list[int | None] = [
                int(p) for p in self.source.config.get("project_ids") or []
            ] or [None]
            cameras: dict[int, dict[str, Any]] = {}
            for project_id in project_ids:
                cameras.update(await client.cameras(project_id))
        finally:
            await client.close()
        return [
            {
                "external_id": str(camera_id),
                "name": camera.get("name"),
                "device_id": camera.get("device_id"),
                "site": (camera.get("current_site") or {}).get("name"),
                "attributes": {
                    "addaxai_project_id": camera.get("project_id"),
                    "location": camera.get("location"),
                },
            }
            for camera_id, camera in cameras.items()
        ]

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "cameras": len(await self.list_devices())}


class AddaxAiConnectAdapter:
    key: ClassVar[str] = "addaxai_connect"
    label: ClassVar[str] = "AddaxAI Connect"
    push: ClassVar[bool] = False
    polling: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.API
    config_example: ClassVar[dict[str, Any]] = {
        "url": "https://connect.example.org",
        "web_url": "https://connect.example.org",
        "project_ids": [],
        "poll_interval_seconds": 300,
        "overlap_days": 7,
        "min_confidence": 0.5,
        "species": [],
        "categories": ["animal"],
        "verified_only": False,
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "email": "Email of a dedicated AddaxAI Connect viewer account",
        "password": "Its password",
    }
    setup_hint: ClassVar[str] = (
        "Create a viewer account in AddaxAI Connect for this server. Each camera becomes an "
        "identity; create a camera device with the Generic JSON driver and link it, or accept "
        "it from Needs attention. Detections arrive as SPECIES_DETECTION events."
    )
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True, device_management=True
    )
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "poll",
            "label": "API polling",
            "direction": "in",
            "purpose": "The ingest service polls the server for new detections",
            "config_keys": ["url"],
            "optional_keys": [
                "project_ids",
                "poll_interval_seconds",
                "overlap_days",
                "rescan_interval_hours",
                "min_confidence",
                "species",
                "categories",
                "verified_only",
            ],
            "credential_keys": ["email", "password"],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/projects/{addaxai_project_id}/cameras",
        "OPEN_APPLICATION": "{web_url}/projects/{addaxai_project_id}/images",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "AddaxAI Connect server"},
            "web_url": {"type": "string", "description": "Web app, for deep links"},
            "project_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "AddaxAI Connect project ids; empty means every project",
            },
            "poll_interval_seconds": {"type": "integer", "default": 300, "minimum": 30},
            "overlap_days": {"type": "number", "default": 7},
            "rescan_interval_hours": {"type": "number", "default": 24},
            "min_confidence": {"type": "number", "default": 0.5, "minimum": 0, "maximum": 1},
            "species": {"type": "array", "items": {"type": "string"}},
            "categories": {
                "type": "array",
                "items": {"type": "string", "enum": ["animal", "person", "vehicle"]},
            },
            "verified_only": {"type": "boolean", "default": False},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return AddaxAiConnector(source)

    def management_connector(self, source: DataSourceContext) -> AddaxAiManagement:
        return AddaxAiManagement(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        """No webhook today (D16); a future AddaxAI Connect push would post image items."""
        if isinstance(body, dict) and body.get("uuid"):
            message = parse_image(source, body, body.get("camera"))
            return [message] if message is not None else []
        raise _error("AddaxAI Connect pushes are not configured; the connector polls")


__all__ = ["AddaxAiConnectAdapter", "AddaxAiConnector", "parse_image"]

# The poll loop sleeps between polls; a cancelled poll must not leave a client open.
_ = asyncio
