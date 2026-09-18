"""The vegetation mosaic of the grazing analysis (Tim, 2026-09-18: one colour per area is no
map): the grid that covers the areas, and the bound that coarsens it rather than refusing."""

import uuid

from shapely.geometry import shape

from shared.analysis.modules.grazing import (
    MAX_VEGETATION_CELLS,
    Area,
    cell_geojson,
    vegetation_grid,
)


def _area(name: str, west: float, south: float, size: float) -> Area:
    geojson = {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [west + size, south],
                [west + size, south + size],
                [west, south + size],
                [west, south],
            ]
        ],
    }
    return Area(uuid.uuid4(), name, "zone", shape(geojson), geojson, 0.0)


def test_the_grid_covers_the_area_with_many_cells():
    """A single area is a mosaic of cells, not one polygon: that was the whole complaint."""
    area = _area("Horsterwold", 5.50, 52.35, 0.02)  # about 1.3 by 2.2 km
    grid, cells = vegetation_grid([area], 100)
    keys = cells[area.id]
    assert len(keys) > 50, "a square kilometre at 100 m is hundreds of cells"
    assert grid.cell_m == 100
    # every cell's centre lies in the area, and the cells do not repeat
    assert len(set(keys)) == len(keys)
    for key in keys:
        ring = cell_geojson(grid, key)["coordinates"][0]
        centre_lon = sum(p[0] for p in ring[:4]) / 4
        centre_lat = sum(p[1] for p in ring[:4]) / 4
        assert area.geometry.contains(
            shape({"type": "Point", "coordinates": [centre_lon, centre_lat]})
        )


def test_a_large_selection_is_drawn_coarser_rather_than_refused():
    """Bounds answer rather than refuse (architecture 13.10, decision D148)."""
    big = _area("Whole park", 16.60, -20.90, 0.30)  # tens of kilometres
    grid, cells = vegetation_grid([big], 100)
    assert sum(len(c) for c in cells.values()) <= MAX_VEGETATION_CELLS
    assert grid.cell_m > 100, "the cell size grew until the park fitted"


def test_every_area_of_a_selection_gets_its_own_cells():
    west = _area("West", 5.50, 52.35, 0.01)
    east = _area("East", 5.54, 52.35, 0.01)
    _grid, cells = vegetation_grid([west, east], 100)
    assert cells[west.id] and cells[east.id]
    assert not set(cells[west.id]) & set(cells[east.id]), "the two areas share no cell"
    assert sum(len(c) for c in cells.values()) <= MAX_VEGETATION_CELLS


def test_an_area_smaller_than_one_cell_gets_nothing_rather_than_a_wrong_cell():
    """No cell centre inside means no mosaic for it; the area's own mean still stands."""
    tiny = _area("Hide", 5.50, 52.35, 0.0001)  # about 10 m
    _grid, cells = vegetation_grid([tiny], 1000)
    assert cells[tiny.id] == []
