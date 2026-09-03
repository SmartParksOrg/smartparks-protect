#!/usr/bin/env python3
"""Prepare the local ChirpStack for OpenCollar testing and register it as a data source.

Everything is created through the ChirpStack REST API and the Smart Parks Protect API.
Re-running is safe: existing objects are reused by name or id.

The ChirpStack API key: pass one made in the web UI (http://localhost:8080, admin / admin,
Network Server, API keys, global key) with --chirpstack-api-key, or let the script mint one for
the local compose stack with --mint-key. Minting inserts a row into ChirpStack's `api_key` table
through `docker exec` and signs a JWT with CHIRPSTACK_API_SECRET from `.env`; ChirpStack keys
are exactly that, so the result is a normal key. Development only.

    uv run scripts/chirpstack_bootstrap.py --mint-key --demo \
        --protect-email admin@example.org --protect-password '...' \
        [--codec shared/shared/device_drivers/opencollar/codec.js]
"""

import argparse
import os
import secrets
import subprocess
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any

import httpx
import jwt

TENANT_NAME = "Smart Parks (dev)"
APPLICATION_NAME = "OpenCollar"
PROFILE_NAME = "OpenCollar EU868"
GATEWAY_ID = "0016c001f153a14c"
DEVICE_EUI = "70b3d57ed0001234"
DATA_SOURCE_NAME = "ChirpStack (local)"


class ChirpStack:
    def __init__(self, url: str, key: str) -> None:
        self.client = httpx.Client(
            base_url=url, headers={"Grpc-Metadata-Authorization": f"Bearer {key}"}, timeout=15
        )

    def _find(self, path: str, name: str, params: dict[str, Any]) -> dict[str, Any] | None:
        result = self.client.get(path, params={**params, "limit": 100}).raise_for_status().json()
        return next((r for r in result.get("result", []) if r.get("name") == name), None)

    def tenant(self) -> str:
        existing = self._find("/api/tenants", TENANT_NAME, {})
        if existing:
            return str(existing["id"])
        body = {
            "tenant": {
                "name": TENANT_NAME,
                "canHaveGateways": True,
                "maxGatewayCount": 0,
                "maxDeviceCount": 0,
            }
        }
        return str(self.client.post("/api/tenants", json=body).raise_for_status().json()["id"])

    def application(self, tenant_id: str) -> str:
        existing = self._find("/api/applications", APPLICATION_NAME, {"tenantId": tenant_id})
        if existing:
            return str(existing["id"])
        body = {
            "application": {
                "name": APPLICATION_NAME,
                "tenantId": tenant_id,
                "description": "Smart Parks Protect development",
            }
        }
        return str(self.client.post("/api/applications", json=body).raise_for_status().json()["id"])

    def device_profile(self, tenant_id: str, codec: str | None) -> str:
        existing = self._find("/api/device-profiles", PROFILE_NAME, {"tenantId": tenant_id})
        profile = {
            "name": PROFILE_NAME,
            "tenantId": tenant_id,
            "region": "EU868",
            "macVersion": "LORAWAN_1_0_3",
            "regParamsRevision": "A",
            "adrAlgorithmId": "default",
            "supportsOtaa": True,
            "supportsClassB": False,
            "supportsClassC": False,
            "uplinkInterval": 3600,
            "flushQueueOnActivate": True,
            "payloadCodecRuntime": "JS" if codec else "NONE",
            "payloadCodecScript": codec or "",
        }
        if existing:
            self.client.put(
                f"/api/device-profiles/{existing['id']}",
                json={"deviceProfile": {**profile, "id": existing["id"]}},
            ).raise_for_status()
            return str(existing["id"])
        return str(
            self.client.post("/api/device-profiles", json={"deviceProfile": profile})
            .raise_for_status()
            .json()["id"]
        )

    def gateway(self, tenant_id: str) -> None:
        response = self.client.get(f"/api/gateways/{GATEWAY_ID}")
        if response.status_code == 200:
            return
        body = {
            "gateway": {
                "gatewayId": GATEWAY_ID,
                "name": "Simulated gateway",
                "tenantId": tenant_id,
                "statsInterval": 30,
                "location": {"latitude": -24.9, "longitude": 31.5},
            }
        }
        self.client.post("/api/gateways", json=body).raise_for_status()

    def device(self, application_id: str, profile_id: str) -> None:
        response = self.client.get(f"/api/devices/{DEVICE_EUI}")
        if response.status_code == 200:
            return
        body = {
            "device": {
                "devEui": DEVICE_EUI,
                "name": "SP05-sim",
                "applicationId": application_id,
                "deviceProfileId": profile_id,
                "description": "Simulated OpenCollar",
            }
        }
        self.client.post("/api/devices", json=body).raise_for_status()
        key = secrets.token_hex(16)
        self.client.post(
            f"/api/devices/{DEVICE_EUI}/keys",
            json={"deviceKeys": {"devEui": DEVICE_EUI, "nwkKey": key, "appKey": key}},
        ).raise_for_status()


def mint_key(env_file: Path, container: str = "protect-chirpstack-postgres") -> str:
    """A global admin API key for the local ChirpStack, without touching the web UI."""
    secret = None
    for line in env_file.read_text().splitlines():
        if line.startswith("CHIRPSTACK_API_SECRET="):
            secret = line.split("=", 1)[1].strip()
    if not secret:
        raise SystemExit("CHIRPSTACK_API_SECRET not found in .env")
    key_id = str(uuid.uuid4())
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "chirpstack",
            "-d",
            "chirpstack",
            "-q",
            "-c",
            f"insert into api_key (id, created_at, name, is_admin, tenant_id, is_read_only) values ('{key_id}', now(), 'protect-dev-bootstrap', true, null, false)",
        ],
        check=True,
        capture_output=True,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return str(
            jwt.encode(
                {"aud": "chirpstack", "iss": "chirpstack", "sub": key_id, "typ": "key"},
                secret,
                algorithm="HS256",
            )
        )


def register_data_source(
    protect_url: str,
    email: str,
    password: str,
    *,
    tenant_id: str,
    api_key: str,
    application_id: str,
) -> str:
    client = httpx.Client(base_url=protect_url, timeout=15)
    token = (
        client.post("/api/v1/auth/login", data={"username": email, "password": password})
        .raise_for_status()
        .json()["access_token"]
    )
    headers = {"Authorization": f"Bearer {token}"}
    sources = client.get("/api/v1/data-sources", headers=headers).raise_for_status().json()["items"]
    body = {
        "name": DATA_SOURCE_NAME,
        "adapter_key": "chirpstack",
        "config": {
            "mqtt_host": "chirpstack-mosquitto",
            "mqtt_port": 1883,
            "api_url": "http://chirpstack-rest-api:8090",
            "web_url": "http://localhost:8080",
            "tenant_id": tenant_id,
            "application_id": application_id,
        },
        "credentials": {"api_token": api_key},
    }
    existing = next((s for s in sources if s["name"] == DATA_SOURCE_NAME), None)
    if existing:
        client.patch(
            f"/api/v1/data-sources/{existing['id']}",
            json={k: v for k, v in body.items() if k in ("config", "credentials")},
            headers=headers,
        ).raise_for_status()
        return str(existing["id"])
    return str(
        client.post("/api/v1/data-sources", json=body, headers=headers)
        .raise_for_status()
        .json()["id"]
    )


def _find_or_create(
    client: httpx.Client, headers: dict[str, str], path: str, match: dict, body: dict
) -> dict:
    """Return the first item whose fields equal `match`, or create one from `body`."""
    items = client.get(path, headers=headers, params={"limit": 500}).raise_for_status().json()
    for item in items["items"] if isinstance(items, dict) else items:
        if all(item.get(k) == v for k, v in match.items()):
            return dict(item)
    return dict(client.post(path, json=body, headers=headers).raise_for_status().json())


def create_demo(protect_url: str, email: str, password: str, source_id: str) -> dict[str, str]:
    """The Protect side of the quick start: a project, the OpenCollar device type, the simulated
    device with its DevEUI on the ChirpStack data source, and an entity carrying it. Idempotent:
    existing rows with the same names are reused."""
    client = httpx.Client(base_url=protect_url, timeout=15)
    token = (
        client.post("/api/v1/auth/login", data={"username": email, "password": password})
        .raise_for_status()
        .json()["access_token"]
    )
    h = {"Authorization": f"Bearer {token}"}
    project = _find_or_create(
        client,
        h,
        "/api/v1/projects",
        {"slug": "demo-park"},
        {"name": "Demo park", "slug": "demo-park"},
    )
    scopes = (
        client.get(f"/api/v1/data-sources/{source_id}", headers=h)
        .raise_for_status()
        .json()["project_ids"]
    )
    if project["id"] not in scopes:
        client.patch(
            f"/api/v1/data-sources/{source_id}",
            json={"project_ids": [*scopes, project["id"]]},
            headers=h,
        ).raise_for_status()
    entity_type = _find_or_create(
        client,
        h,
        "/api/v1/entity-types",
        {"key": "rhino"},
        {"key": "rhino", "label": "Rhino", "group_key": "tracked", "icon_key": "wildlife.rhino"},
    )
    device_type = _find_or_create(
        client,
        h,
        "/api/v1/device-types",
        {"key": "opencollar_edge"},
        {
            "key": "opencollar_edge",
            "label": "OpenCollar Edge",
            "driver_key": "opencollar",
            "manufacturer": "Smart Parks",
        },
    )
    device = _find_or_create(
        client,
        h,
        "/api/v1/devices",
        {"name": "SP05-sim"},
        {"device_type_id": device_type["id"], "name": "SP05-sim", "status": "active"},
    )
    detail = client.get(f"/api/v1/devices/{device['id']}", headers=h).raise_for_status().json()
    if not any(i["external_id"].lower() == DEVICE_EUI for i in detail["external_identities"]):
        client.post(
            f"/api/v1/devices/{device['id']}/identities",
            json={"data_source_id": source_id, "external_id": DEVICE_EUI.upper()},
            headers=h,
        ).raise_for_status()
    since = "2026-01-01T00:00:00Z"
    if not detail["project_assignments"]:
        client.post(
            f"/api/v1/devices/{device['id']}/project-assignments",
            json={"project_id": project["id"], "valid_from": since},
            headers=h,
        ).raise_for_status()
    entity = _find_or_create(
        client,
        h,
        f"/api/v1/projects/{project['id']}/entities",
        {"name": "Rhino 14"},
        {"entity_type_id": entity_type["id"], "name": "Rhino 14"},
    )
    if not detail["entity_assignments"]:
        client.post(
            f"/api/v1/projects/{project['id']}/entity-assignments",
            json={"device_id": device["id"], "entity_id": entity["id"], "valid_from": since},
            headers=h,
        ).raise_for_status()
    return {"project": project["id"], "device": device["id"], "entity": entity["id"]}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--chirpstack-url", default="http://localhost:8090")
    parser.add_argument("--chirpstack-api-key", help="global API key made in the ChirpStack web UI")
    parser.add_argument(
        "--mint-key", action="store_true", help="mint a key for the local compose stack"
    )
    parser.add_argument(
        "--env-file", type=Path, default=Path(os.environ.get("PROTECT_ENV_FILE", ".env"))
    )
    parser.add_argument("--protect-url", default="http://localhost:8000")
    parser.add_argument("--protect-email")
    parser.add_argument("--protect-password")
    parser.add_argument("--codec", type=Path, help="JavaScript codec for the device profile")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="also create the Protect project, device type, device and entity for the simulator",
    )
    args = parser.parse_args()

    if not args.chirpstack_api_key and not args.mint_key:
        parser.error("give --chirpstack-api-key or --mint-key")
    api_key = args.chirpstack_api_key or mint_key(args.env_file)
    cs = ChirpStack(args.chirpstack_url, api_key)
    tenant_id = cs.tenant()
    application_id = cs.application(tenant_id)
    profile_id = cs.device_profile(tenant_id, args.codec.read_text() if args.codec else None)
    cs.gateway(tenant_id)
    cs.device(application_id, profile_id)
    sys.stdout.write(
        f"tenant {tenant_id}\napplication {application_id}\ndevice profile {profile_id}\ngateway {GATEWAY_ID}\ndevice {DEVICE_EUI}\n"
    )
    if args.protect_email and args.protect_password:
        source_id = register_data_source(
            args.protect_url,
            args.protect_email,
            args.protect_password,
            tenant_id=tenant_id,
            api_key=api_key,
            application_id=application_id,
        )
        sys.stdout.write(f"protect data source {source_id}\n")
        if args.demo:
            demo = create_demo(
                args.protect_url, args.protect_email, args.protect_password, source_id
            )
            sys.stdout.write("".join(f"protect {k} {v}\n" for k, v in demo.items()))
        sys.stdout.write(
            f"simulate: uv run scripts/simulate_opencollar.py --dev-eui {DEVICE_EUI} --application-id {application_id}\n"
        )


if __name__ == "__main__":
    main()
