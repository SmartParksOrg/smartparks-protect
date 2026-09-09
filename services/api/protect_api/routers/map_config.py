"""What the map needs from the server (phase 19, decision D141): the MapTiler key for satellite
imagery and terrain, served at runtime because the frontend image is built once for every server.
The key is public by nature (it reaches every browser) and restricted at MapTiler by referrer."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from protect_api.auth.users import current_active_user
from shared.config import get_settings
from shared.models import User

router = APIRouter(tags=["map"])


class MapConfig(BaseModel):
    maptiler_key: str | None


@router.get("/map/config", response_model=MapConfig)
async def map_config(_: User = Depends(current_active_user)) -> MapConfig:
    return MapConfig(maptiler_key=get_settings().maptiler_key or None)
