"""Protect Go signed in from the Offload page (decision D333): a signed-in person mints a
one-time code, the app exchanges it once for a token that lasts weeks and carries the account."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from shared.models import AuditLog
from tests.api.conftest import actor

pytestmark = pytest.mark.asyncio


async def test_code_exchanged_once_for_a_long_lived_token(client, db):
    person = await actor(client, db)
    minted = await client.post(
        "/api/v1/auth/go-handoff", headers={"Authorization": f"Bearer {person.token}"}
    )
    assert minted.status_code == 200, minted.text
    code = minted.json()["code"]
    assert len(code) >= 32 and minted.json()["expires_in"] == 120

    exchanged = await client.post("/api/v1/auth/go-handoff/exchange", json={"code": code})
    assert exchanged.status_code == 200, exchanged.text
    token = exchanged.json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["sub"] == str(person.user.id)
    life = datetime.fromtimestamp(claims["exp"], tz=UTC) - datetime.now(UTC)
    assert timedelta(days=29) < life <= timedelta(days=30)

    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == person.user.email

    again = await client.post("/api/v1/auth/go-handoff/exchange", json={"code": code})
    assert again.status_code == 404
    actions = list(
        await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.user_id == person.user.id)
            .where(AuditLog.action.like("go_handoff.%"))
        )
    )
    assert sorted(actions) == ["go_handoff.exchange", "go_handoff.issue"]


async def test_unknown_or_malformed_codes_are_refused(client):
    unknown = await client.post(
        "/api/v1/auth/go-handoff/exchange", json={"code": "nobody-minted-this-code-0123456789"}
    )
    assert unknown.status_code == 404
    malformed = await client.post("/api/v1/auth/go-handoff/exchange", json={"code": "short"})
    assert malformed.status_code == 422


async def test_minting_needs_a_login(client):
    response = await client.post("/api/v1/auth/go-handoff")
    assert response.status_code == 401
