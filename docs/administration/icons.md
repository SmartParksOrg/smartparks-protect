# Icons

## The built-in registry

Every entity type, device type and event marker draws a key from the icon registry
(`services/frontend/src/assets/icons/icon-registry.json`, architecture 24). The registry holds
about 350 monochrome silhouettes in six categories: wildlife, people, vehicles, infrastructure,
devices and events. Most of them are EarthRanger's icons, vendored from the open source
EarthRanger server (PADAS/er-server, Apache License 2.0; the licence text sits next to the files
as `LICENSE-EarthRanger`) under decision D165, so an animal or a report looks the same in both
tools. The OpenCollar icon and the alert marker are Smart Parks Protect's own.

Every icon is a square `currentColor` silhouette, so the marker's state colour applies to any of
them, and a species falls back through its group to the generic animal (a jackal to the canid, a
canid to the paw). Wildlife silhouettes face left, EarthRanger's convention for the male icon;
there are no separate female icons.

Choosing an icon: the entity type and device type dialogs under Server admin open a searchable
list grouped by category; the search matches the label, the key and the aliases (a Latin name,
a synonym such as "gnu" for the wildebeest). Events take their icon from the event type: geofence
entered and exited, no data, low battery, immobility, speeding, proximity and species detection
have one each, every other type shows the alert marker.

Adding icons: `scripts/import_earthranger_icons.py` lists every vendored icon with its source
file at a pinned commit of the EarthRanger repository; add a line, run the script (it downloads,
normalises and rewrites the registry) and commit the result. An icon EarthRanger lacks is drawn
by hand as a square `currentColor` SVG in the matching folder with a registry entry of its own.

## Custom icons

Projects may upload their own SVG icons (architecture 24.6, decision D84): Project admin,
Settings, "Custom icons". An uploaded icon gets the key `project.<slug>` and can be chosen as
the icon key of an entity type, a device type or an entity, next to the built-in registry.

Validation: at most 64 KB, a well-formed `<svg>` root, no `<script>`, `<foreignObject>`,
`<image>`, `<iframe>`, `<embed>`, `<object>` or animation elements, no `on*` handlers, no
external `href` (only `#` references), no `url()` in styles, no DOCTYPE or entities. Colour
follows the text colour when the SVG uses `currentColor`.

The frontend loads the project's icons when a project is opened; the icon component prefers a
project icon over the registry for `project.*` keys and falls back to the registry when the
project has none. Uploading with an existing key replaces the icon; deleting it makes the
types fall back to the category's default icon.
