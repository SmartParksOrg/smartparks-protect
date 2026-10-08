"""A project's raster layers (phase 41, decision D315): an upload of a GeoTIFF read without a
raster library, the list, the catalogue of what a habitat run may name (the uploads and a
distance layer per feature type the project has), the deletion, the refusals (no CRS, two
bands, a reserved name, a name taken) and the permissions (features:write to upload, a
viewer reads)."""

import uuid

import pytest

from shared.enums import Role
from tests.api.conftest import create_project, project_actor
from tests.conftest import unique_name
from tests.shared.test_geotiff import _geokeys, _tiff

pytestmark = pytest.mark.asyncio


def _layer_file(bands: int = 1, *, epsg: int = 32733) -> bytes:
    return _tiff(
        [
            (256, 4, [120]),
            (257, 4, [80]),
            (258, 3, [32]),
            (277, 3, [bands]),
            (339, 3, [3]),
            (33550, 12, [30.0, 30.0, 0.0]),
            (33922, 12, [0.0, 0.0, 0.0, 500_000.0, 7_700_000.0, 0.0]),
            (34735, 3, _geokeys(1, 3072, epsg)),
            (42113, 2, ["-9999"]),
        ]
    )


async def _upload(client, headers, project_id, name: str, data: bytes, **query):
    return await client.post(
        f"/api/v1/projects/{project_id}/layers",
        params={"name": name, "label": query.pop("label", name.title()), **query},
        files={"file": (f"{name}.tif", data, "image/tiff")},
        headers=headers,
    )


async def test_upload_list_catalogue_and_delete(client, db):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    base = f"/api/v1/projects/{project.id}"

    # a site, so the catalogue offers a distance layer for it
    site = await client.post(
        f"{base}/features",
        json={
            "feature_type": "site",
            "name": unique_name("Waterhole"),
            "geometry": {"type": "Point", "coordinates": [16.73, -20.84]},
        },
        headers=admin.headers,
    )
    assert site.status_code == 201, site.text

    created = await _upload(client, admin.headers, project.id, "soil_clay", _layer_file())
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["epsg"] == 32733 and (row["width"], row["height"]) == (120, 80)
    assert row["pixel_m"] == 30.0 and row["nodata"] == -9999 and row["kind"] == "continuous"
    assert row["extent"] == {
        "west": 500_000.0,
        "south": 7_697_600.0,
        "east": 503_600.0,
        "north": 7_700_000.0,
    }

    listed = await client.get(f"{base}/layers", headers=viewer.headers)
    assert listed.status_code == 200 and [r["name"] for r in listed.json()] == ["soil_clay"]

    choices = await client.get(f"{base}/analysis-layers", headers=viewer.headers)
    assert choices.status_code == 200, choices.text
    by_name = {c["name"]: c for c in choices.json()}
    assert by_name["soil_clay"]["source"] == "project"
    assert by_name["soil_clay"]["layer_id"] == row["id"]
    assert by_name["distance_to_site"]["source"] == "distance"
    assert by_name["distance_to_site"]["feature_type"] == "site"
    assert "distance_to_route" not in by_name  # the project has no route
    # no environmental provider on the test server: no NDVI or elevation offered
    assert "ndvi" not in by_name

    gone = await client.delete(f"{base}/layers/{row['id']}", headers=admin.headers)
    assert gone.status_code == 204
    assert (await client.get(f"{base}/layers", headers=viewer.headers)).json() == []
    assert (
        await client.delete(f"{base}/layers/{uuid.uuid4()}", headers=admin.headers)
    ).status_code == 404


async def test_refusals_and_permissions(client, db):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    h = admin.headers

    forbidden = await _upload(client, viewer.headers, project.id, "soil", _layer_file())
    assert forbidden.status_code == 403

    no_crs = _tiff([(256, 3, [10]), (257, 3, [10])])
    assert (await _upload(client, h, project.id, "soil", no_crs)).status_code == 422
    assert (
        "georeferencing" in (await _upload(client, h, project.id, "soil", no_crs)).json()["detail"]
    )

    two = await _upload(client, h, project.id, "soil", _layer_file(bands=2))
    assert two.status_code == 422 and "2 bands" in two.json()["detail"]

    reserved = await _upload(client, h, project.id, "ndvi", _layer_file())
    assert reserved.status_code == 422 and "Protect makes itself" in reserved.json()["detail"]
    distance = await _upload(client, h, project.id, "distance_to_site", _layer_file())
    assert distance.status_code == 422

    bad_name = await _upload(client, h, project.id, "Soil Clay", _layer_file())
    assert bad_name.status_code == 422 and "band name" in bad_name.json()["detail"]

    assert (await _upload(client, h, project.id, "soil", _layer_file())).status_code == 201
    taken = await _upload(client, h, project.id, "soil", _layer_file())
    assert taken.status_code == 409

    categorical = await _upload(
        client, h, project.id, "landcover", _layer_file(), kind="categorical"
    )
    assert categorical.status_code == 201 and categorical.json()["kind"] == "categorical"
    wrong_kind = await _upload(client, h, project.id, "other", _layer_file(), kind="fuzzy")
    assert wrong_kind.status_code == 422
