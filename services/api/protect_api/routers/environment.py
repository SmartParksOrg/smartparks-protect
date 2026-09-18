"""Environmental data providers as a server admin sets them up (decision D250). The grazing
analysis reads a vegetation index per management area from an outside provider; its account
belonged to the server's environment variables, which put the setup out of reach of the people
who run the server. The credentials live in `server_settings` now, the secret encrypted the way
a data source's credentials are, and a change takes effect without a restart."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.deps import require_server_admin
from protect_api.schemas.platform import (
    EnvironmentProviderRead,
    EnvironmentProviderUpdate,
    EnvironmentTestResult,
)
from shared.analysis.environment import PROVIDER_SETTING, provider_for
from shared.analysis.providers.copernicus import ProviderError
from shared.config import get_settings
from shared.database import get_session
from shared.models import ServerSetting, User
from shared.secrets import encrypt_json

router = APIRouter(
    prefix="/admin/environment",
    tags=["environment"],
    dependencies=[Depends(require_server_admin)],
)

#: The one provider there is today; the shape allows more without a migration.
COPERNICUS = "copernicus"


async def _stored(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(ServerSetting, PROVIDER_SETTING)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    config = value.get(COPERNICUS)
    return config if isinstance(config, dict) else {}


def _read(config: dict[str, Any]) -> EnvironmentProviderRead:
    """Never the secret itself, only whether one is stored, as the data source form does."""
    settings = get_settings()
    from_env = settings.landscape_configured
    has_secret = bool(config.get("client_secret"))
    return EnvironmentProviderRead(
        key=COPERNICUS,
        label="Copernicus Data Space (Sentinel-2)",
        layers=["ndvi"],
        enabled=bool(config.get("enabled", True)),
        client_id=str(config.get("client_id") or ""),
        secret_set=has_secret,
        configured=bool(config.get("client_id") and has_secret and config.get("enabled", True)),
        from_environment=from_env,
        active=bool(config.get("client_id") and has_secret and config.get("enabled", True))
        or from_env,
    )


@router.get("/providers", response_model=list[EnvironmentProviderRead])
async def list_providers(
    session: AsyncSession = Depends(get_session),
) -> list[EnvironmentProviderRead]:
    """What the server can read environmental layers from, and whether it is set up."""
    return [_read(await _stored(session))]


@router.put("/providers/copernicus", response_model=EnvironmentProviderRead)
async def set_copernicus(
    body: EnvironmentProviderUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> EnvironmentProviderRead:
    """The account the server uses. An omitted secret keeps the one stored, so the page can
    save the client id or the switch without the secret being typed again; an empty secret
    clears it."""
    config = dict(await _stored(session))
    if body.client_id is not None:
        config["client_id"] = body.client_id.strip()
    if body.client_secret is not None:
        config["client_secret"] = (
            encrypt_json({"client_secret": body.client_secret}).decode()
            if body.client_secret.strip()
            else ""
        )
    if body.enabled is not None:
        config["enabled"] = body.enabled
    row = await session.get(ServerSetting, PROVIDER_SETTING)
    value = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    value[COPERNICUS] = config
    if row is None:
        session.add(ServerSetting(key=PROVIDER_SETTING, value=value, updated_by_user_id=user.id))
    else:
        row.value = value
        row.updated_by_user_id = user.id
    await record_audit(
        session,
        user=user,
        action="environment_provider.updated",
        object_type="server_setting",
        object_id=PROVIDER_SETTING,
        # never the secret, only that one was written
        details={
            "provider": COPERNICUS,
            "client_id": config.get("client_id"),
            "secret_set": bool(config.get("client_secret")),
            "enabled": config.get("enabled", True),
        },
    )
    await session.commit()
    return _read(config)


@router.post("/providers/copernicus/test", response_model=EnvironmentTestResult)
async def test_copernicus(session: AsyncSession = Depends(get_session)) -> EnvironmentTestResult:
    """Ask the provider for a token and the collection, which costs no processing quota. The
    stored account is tested, or the environment's when nothing is stored."""
    from shared.analysis.environment import stored_providers

    provider = next(
        (p for p in await stored_providers(session) if "ndvi" in p.layers),
        provider_for("ndvi"),
    )
    if provider is None:
        return EnvironmentTestResult(ok=False, detail="No account is set up for this provider.")
    check = getattr(provider, "check", None)
    if check is None:
        return EnvironmentTestResult(ok=False, detail="This provider cannot be tested.")
    try:
        return EnvironmentTestResult(ok=True, detail=await check())
    except ProviderError as refused:
        return EnvironmentTestResult(ok=False, detail=str(refused))
    except Exception as failed:
        return EnvironmentTestResult(
            ok=False, detail=f"The provider could not be reached: {failed}"
        )
