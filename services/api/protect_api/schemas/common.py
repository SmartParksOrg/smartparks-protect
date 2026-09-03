from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GeoJSONGeometry(BaseModel):
    type: str = Field(
        pattern="^(Point|LineString|Polygon|MultiPoint|MultiLineString|MultiPolygon)$"
    )
    coordinates: list[Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "coordinates": self.coordinates}
