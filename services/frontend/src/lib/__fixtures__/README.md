# Fixtures for the import tests

Written on 2026-10-01 with GeoPandas 1.2.0 (`GeoDataFrame.to_parquet`, `schema_version="1.1.0"`)
and pyarrow 25.0.1, the way QGIS, ArcGIS and Ecoscope users hand over a file, and kept as base64
text (`.b64`) so the tests import them through Vite's `?raw` without Node file access:

- `areas.parquet.b64`: a polygon named "North block" and a line named "Patrol road", snappy compressed, GeoParquet 1.1.0 with the CRS EPSG:4326 in the metadata.
- `camp-zstd.parquet.b64`: one point named under `NAME`, zstd compressed, CRS OGC:CRS84.
- `plain.parquet.b64`: a Parquet file without a geometry column or GeoParquet metadata, which the import refuses.

To make one again: `base64 -w0 file.parquet > file.parquet.b64`.
