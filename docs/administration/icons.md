# Custom icons

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
