# openEO answers

`ndvi_timeseries.json`: what the Copernicus Data Space openEO backend wrote for a weekly mean
NDVI over two polygons near Okonjima (16.70 to 16.76 east, 20.83 to 20.86 south) between
1 July and 1 September 2026, recorded from the live API on 2026-09-17 with Smart Parks'
own client. The job took about four and a half minutes and cost 5 credits.

The shape the provider parses: a mapping from the week's timestamp to one list per geometry,
each holding one value per band (one band here). The backend labels a week by its Sunday, a
day before the Monday Protect counts from, so `sample_weekly` matches each answer to the
nearest week it asked for.
