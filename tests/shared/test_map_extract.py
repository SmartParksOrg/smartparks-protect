"""The offline map of a project's area (phase 43 P3): the box padded, the newest planet build
found by probing backwards, and `pmtiles extract` cutting a box out of a planet, run on a small
world of our own making so the test needs no network and no 140 GB."""

import shutil
from datetime import date
from pathlib import Path

import httpx
import pytest
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

from shared.maps.extract import Bbox, MapExtractError, extract, latest_planet_build, pad

WORLD = Bbox(-180.0, -85.0511, 180.0, 85.0511)


def make_planet(path: Path, max_zoom: int = 4) -> int:
    """A PMTiles archive with every tile of zoom 0 to `max_zoom`, each holding its own name,
    written in tile id order (clustered), which `pmtiles extract` requires of its source."""
    tiles = sorted(
        (zxy_to_tileid(z, x, y), f"{z}/{x}/{y}".encode())
        for z in range(max_zoom + 1)
        for x in range(2**z)
        for y in range(2**z)
    )
    count = len(tiles)
    with path.open("wb") as handle:
        writer = Writer(handle)
        for tileid, data in tiles:
            writer.write_tile(tileid, data)
        writer.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.NONE,
                "min_zoom": 0,
                "max_zoom": max_zoom,
                "min_lon_e7": int(WORLD.west * 1e7),
                "min_lat_e7": int(WORLD.south * 1e7),
                "max_lon_e7": int(WORLD.east * 1e7),
                "max_lat_e7": int(WORLD.north * 1e7),
                "clustered": True,
                "center_zoom": 0,
                "center_lon_e7": 0,
                "center_lat_e7": 0,
            },
            {"name": "test planet"},
        )
    return count


def tiles_of(path: Path) -> list[tuple[int, int, int]]:
    with path.open("rb") as handle:
        reader = Reader(MmapSource(handle))
        return [zxy for zxy, _data in all_tiles(reader.get_bytes)]


def test_pad_grows_the_box_and_clamps_to_the_world():
    box = pad(Bbox(-10.9, 7.7, -10.8, 7.8), 5.0)
    assert box.west < -10.9 and box.east > -10.8 and box.south < 7.7 and box.north > 7.8
    assert round(box.north - 7.8, 3) == round(5.0 / 111.32, 3)
    edge = pad(Bbox(179.9, 84.9, 180.0, 85.0), 50.0)
    assert edge.east == 180.0 and edge.north == 85.0


def test_a_box_within_another():
    assert Bbox(0, 0, 10, 10).contains(Bbox(1, 1, 9, 9))
    assert not Bbox(0, 0, 10, 10).contains(Bbox(1, 1, 11, 9))


@pytest.mark.asyncio
async def test_the_newest_build_is_found_by_probing_backwards():
    def planet(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.path == "/20261015.pmtiles" else 404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(planet)) as client:
        url, build = await latest_planet_build(client, today=date(2026, 10, 17))
    assert (url, build) == ("https://build.protomaps.com/20261015.pmtiles", "20261015")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404))
    ) as client:
        with pytest.raises(MapExtractError, match="No planet build"):
            await latest_planet_build(client, today=date(2026, 10, 17), lookback=3)


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("pmtiles") is None, reason="the pmtiles command is not installed")
async def test_extract_cuts_the_box_and_the_zoom_out_of_the_planet(tmp_path):
    planet = tmp_path / "planet.pmtiles"
    total = make_planet(planet, max_zoom=4)
    assert total == sum(4**z for z in range(5))
    out = tmp_path / "area.pmtiles"
    # Gola Rainforest, roughly: the east of Sierra Leone, west of Liberia
    await extract(str(planet), Bbox(-11.0, 7.6, -10.8, 7.9), 3, out)
    tiles = tiles_of(out)
    assert tiles, "the extract holds no tile"
    assert max(z for z, _, _ in tiles) == 3
    assert len(tiles) < total
    # every zoom level down to 3 has exactly the tile the box falls in
    assert sorted({z for z, _, _ in tiles}) == [0, 1, 2, 3]
    assert (3, 3, 3) in tiles  # x=floor((-10.9+180)/360*8)=3, y for lat 7.7 at z3 = 3
    with pytest.raises(MapExtractError, match="pmtiles extract failed"):
        await extract(
            str(tmp_path / "missing.pmtiles"), Bbox(0, 0, 1, 1), 2, tmp_path / "x.pmtiles"
        )
