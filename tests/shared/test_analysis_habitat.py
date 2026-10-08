"""The habitat primitives and hrHSA on a synthetic landscape (phase 41): a gradient layer and
a noise layer, animals whose fixes are drawn with probability proportional to exp(β times
the gradient), so the fitted coefficient of the gradient is positive and clear, the noise
coefficient's interval covers zero, the leave-one-individual-out Boyce index is high, the
surface ranks with the gradient, and the grid, the slope, the distance layer and the
relocations behave. Runs where hrHSA is installed (the analysis image) and is skipped
in the lean environment."""

import math
import uuid

import numpy as np
import pytest

from shared.analysis.base import ModuleUnavailable
from shared.analysis.primitives import habitat as hab
from shared.analysis.primitives.trajectory import Trajectory

hsa = pytest.importorskip("hsa.rsf", reason="hrHSA is installed in the analysis image only")

EPSG = 32733  # UTM 33S, around Okonjima
LAT0, LON0 = -20.85, 16.73


def _track(
    rng: np.random.Generator, grad: np.ndarray, grid: hab.Grid, beta: float, n: int, ids: int
) -> Trajectory:
    """Fixes drawn in a box of the grid with probability exp(beta * gradient)."""
    from pyproj import Transformer

    h, w = grad.shape
    cy, cx = rng.integers(h // 4, 3 * h // 4), rng.integers(w // 4, 3 * w // 4)
    ii, jj = np.meshgrid(np.arange(cy - 40, cy + 40), np.arange(cx - 40, cx + 40), indexing="ij")
    weights = np.exp(beta * grad[ii, jj])
    weights /= weights.sum()
    picks = rng.choice(weights.size, size=n, p=weights.ravel())
    xs = grid.west + grid.resolution_m * (jj.ravel()[picks] + rng.uniform(0, 1, n))
    ys = grid.north - grid.resolution_m * (ii.ravel()[picks] + rng.uniform(0, 1, n))
    back = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    lons, lats = back.transform(xs, ys)
    times = 1_760_000_000.0 + 3600.0 * np.arange(n)
    return Trajectory(
        entity_id=uuid.UUID(int=ids),
        times=times,
        lat=np.asarray(lats, dtype=np.float64),
        lon=np.asarray(lons, dtype=np.float64),
        accuracy_m=np.full(n, 10.0),
        satellites=np.full(n, 9.0),
        device_ids=[uuid.UUID(int=ids)] * n,
    )


@pytest.fixture(scope="module")
def landscape():
    rng = np.random.default_rng(7)
    grid = hab.Grid(
        epsg=EPSG,
        resolution_m=30.0,
        west=500_000.0,
        south=7_694_000.0,
        east=506_000.0,
        north=7_700_000.0,
        bbox_wgs84=(16.0, -21.0, 17.0, -20.0),
    )
    n = grid.height
    grad = np.tile(np.linspace(-1, 1, grid.width), (n, 1))
    noise = rng.normal(size=(n, grid.width))
    layers = {
        "grad": hab.empty_stack(grid).copy(data=grad.astype("float32")),
        "noise": hab.empty_stack(grid).copy(data=noise.astype("float32")),
    }
    tracks = [_track(rng, grad, grid, 2.0, 400, i + 1) for i in range(6)]
    return grid, layers, tracks


def test_the_grid_covers_the_domains_and_doubles_to_the_bound(landscape):
    _, _, tracks = landscape
    grid = hab.grid_for(tracks, quantile=0.95, buffer_m=500, finest_m=30)
    assert grid.epsg == EPSG and grid.resolution_m == 30.0
    for track in tracks:
        x, y = hab._to_utm(track.lat, track.lon, EPSG)
        assert grid.west <= x.min() and x.max() <= grid.east
        assert grid.south <= y.min() and y.max() <= grid.north
    assert grid.west % 30 == 0 and grid.north % 30 == 0
    coarse = hab.grid_for(tracks, quantile=0.95, buffer_m=500, finest_m=30, max_cells=2_000)
    assert coarse.resolution_m > 30 and coarse.cells <= 2_000
    assert math.log2(coarse.resolution_m / 30).is_integer()


def test_the_fit_recovers_the_gradient_and_validates(landscape):
    grid, layers, tracks = landscape
    env = hab.stack_layers(grid, layers)
    assert list(env["band"].values) == ["grad", "noise"] and env.rio.crs.to_epsg() == EPSG
    reloc = hab.relocations(tracks, {}, grid.epsg)
    assert len(reloc) == 2400 and reloc.crs.to_epsg() == EPSG
    assert str(reloc["time"].dt.tz) == "UTC"
    fit = hab.fit_rsf(
        reloc,
        env,
        linear=["grad", "noise"],
        quadratic=[],
        categorical=[],
        domain_quantile=0.95,
        sampling_factor=10,
        thin_hours=None,
        loio=True,
    )
    by_term = {c.term: c for c in fit.coefficients}
    assert set(by_term) == {"const", "grad", "noise"}
    assert by_term["grad"].estimate > 0.15 and by_term["grad"].lower > 0
    assert by_term["noise"].lower < 0 < by_term["noise"].upper
    assert fit.converged and fit.used == 2400 and fit.available == 24_000
    assert set(fit.scaling) == {"grad", "noise"}
    assert len(fit.folds) == 6
    assert all(f.error is None and f.boyce is not None and f.boyce > 0.6 for f in fit.folds)
    assert all(len(f.curve) >= 5 for f in fit.folds)
    # the surface rises with the gradient: the east reads higher than the west
    surface = fit.surface.values
    assert np.nanmean(surface[:, -20:]) > np.nanmean(surface[:, :20]) * 1.5
    cells = hab.surface_cells(fit.surface, grid, LAT0, LON0, max_cells=400)
    assert 0 < len(cells.cells) <= 400 and len(cells.breaks) == 5
    ranks = [c[3] for c in cells.cells]
    assert min(ranks) == 0 and max(ranks) == 4
    assert cells.breaks == sorted(cells.breaks)


def test_two_animals_skip_nothing_but_loio_is_the_modules_call(landscape):
    grid, layers, tracks = landscape
    env = hab.stack_layers(grid, layers)
    reloc = hab.relocations(tracks[:2], {}, grid.epsg)
    fit = hab.fit_rsf(
        reloc,
        env,
        linear=["grad"],
        quadratic=["grad"],
        categorical=[],
        domain_quantile=0.9,
        sampling_factor=5,
        thin_hours=2,
        loio=False,
    )
    assert {c.term for c in fit.coefficients} == {"const", "grad", "grad__sq"}
    assert fit.folds == [] and fit.used < 800  # thinned to every two hours


def test_slope_and_distance_layers(landscape):
    grid, _, _ = landscape
    # a plane rising 1 m per 10 m eastward is a slope of about 5.7 degrees everywhere inside
    x = np.arange(grid.width) * grid.resolution_m
    elevation = hab.empty_stack(grid).copy(data=np.tile(x / 10, (grid.height, 1)).astype("float32"))
    slope = hab.slope_from_elevation(elevation)
    inner = slope.values[2:-2, 2:-2]
    assert np.allclose(inner, math.degrees(math.atan(0.1)), atol=0.05)
    from pyproj import Transformer

    # a site at the grid's middle (the test's grid sits at 15 east, zone 33's meridian)
    fx, fy = (grid.west + grid.east) / 2, (grid.south + grid.north) / 2
    site_lon, site_lat = Transformer.from_crs(
        f"EPSG:{EPSG}", "EPSG:4326", always_xy=True
    ).transform(fx, fy)
    site = {"type": "Point", "coordinates": [float(site_lon), float(site_lat)]}
    distance = hab.distance_layer(grid, [site])
    col = int((fx - grid.west) // grid.resolution_m)
    row = int((grid.north - fy) // grid.resolution_m)
    assert distance.values[row, col] < grid.resolution_m
    assert abs(distance.values[row, min(grid.width - 1, col + 100)] - 3000) < 60
    empty = hab.distance_layer(grid, [])
    assert np.isnan(empty.values).all()


def test_a_geotiff_round_trips_onto_the_grid(landscape):
    import io

    import rasterio
    from rasterio.transform import from_origin

    grid, layers, _ = landscape
    # the gradient written at 90 m in the same CRS and read back onto the 30 m grid
    coarse = layers["grad"].values[::3, ::3]
    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        width=coarse.shape[1],
        height=coarse.shape[0],
        count=1,
        dtype="float32",
        crs=f"EPSG:{EPSG}",
        transform=from_origin(grid.west, grid.north, 90, 90),
        nodata=-9999,
    ) as dst:
        dst.write(coarse, 1)
    layer = hab.layer_from_geotiff(buffer.getvalue(), grid)
    assert layer.shape == (grid.height, grid.width)
    assert np.corrcoef(layer.values.ravel(), layers["grad"].values.ravel())[0, 1] > 0.99


def test_require_engine_is_the_lean_workers_refusal(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("hsa"):
            raise ImportError("no hsa")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ModuleUnavailable, match="analysis image"):
        hab.require_engine()
