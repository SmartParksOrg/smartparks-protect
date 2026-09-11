# Icon assets

`icon-registry.json` maps stable keys (`wildlife.rhino`) to the SVG files in these folders; the
frontend inlines every file at build time (`src/components/icons/registry.ts`).

Most files are EarthRanger's icons, taken from the open source EarthRanger server
(https://github.com/PADAS/er-server, Apache License 2.0, the licence in `LICENSE-EarthRanger`) at
the commit pinned in `scripts/import_earthranger_icons.py`, which downloads and normalises them
(decision D165). The registry entry of every file names its source and licence. Files with the
source "Smart Parks Protect" are drawn here under the repository's MIT licence.

Every file is a square `viewBox` with `fill="currentColor"` and nothing baked in: no styles,
classes, titles, fixed colours or halos. `registry.test.ts` checks that shape.
