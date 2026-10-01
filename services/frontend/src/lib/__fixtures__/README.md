# Fixtures for the import tests

Written on 2026-10-01 with GeoPandas 1.2.0 (`GeoDataFrame.to_parquet`, `schema_version="1.1.0"`)
and pyarrow 25.0.1, the way QGIS, ArcGIS and Ecoscope users hand over a file:

- `areas.parquet`: a polygon named "North block" and a line named "Patrol road", snappy compressed, GeoParquet 1.1.0 with the CRS EPSG:4326 in the metadata.
- `camp-zstd.parquet`: one point named under `NAME`, zstd compressed, CRS OGC:CRS84.
- `plain.parquet`: a Parquet file without a geometry column or GeoParquet metadata, which the import refuses.
