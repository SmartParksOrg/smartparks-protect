# Frontend conventions

Rules for `services/frontend`. They exist so every screen behaves the same on a phone in the field and on a desktop in the office. Read `CONVENTIONS.md` at the repository root first.

## Stack

React 19, Vite, TypeScript strict, Tailwind 4, shadcn/ui (Radix), TanStack Query, Zustand, React Hook Form with Zod, React Router 7, MapLibre GL JS, Apache ECharts, Vitest, Playwright. `npm run build` runs the type check first; a type error fails the build and the Docker image.

## Colour system

Colours are CSS variables in `src/index.css`, exposed to Tailwind through `@theme`. Components use semantic tokens (`bg-primary`, `text-muted-foreground`), never hex values.

| Token | Value | Use |
| --- | --- | --- |
| `--brand-green-dark` | `#52735E` | Primary actions, active navigation, headings on light surfaces |
| `--brand-green-light` | `#90AE9B` | Secondary actions, focus rings, selected states |
| `--brand-sand` | `#C6B187` | Logo variant, warm accents, warning tint |
| `--brand-blue` | `#BED2D4` | Logo variant, informational tint |
| `--brand-coral` | `#EDA08F` | Logo variant, attention tint (not for errors) |
| `--destructive` | `#A13D2D` | Errors and destructive actions |

State colours on the map communicate status, not object type; the icon communicates type. Dark mode is not implemented. Do not add `dark:` classes until a dark palette exists.

## Logo

`src/assets/brand/` holds `logo-stacked.svg` (emblem above wordmark), `logo-wide.svg` (emblem left of wordmark) and `logo-mark.svg` (emblem only). All use `fill="currentColor"`. Import them as React components (`import Logo from "@/assets/brand/logo-mark.svg?react"`) so `className="text-primary"` colours them; an `<img>` cannot inherit the colour. Use the mark for the sidebar and favicon, the wide logo in headers, the stacked logo on the login page.

## Map

- One `useMap` hook per map. The MapLibre worker is bundled by Vite (`?worker&url`) and registered with `setWorkerUrl`; do not import MapLibre elsewhere.
- Symbol layers use `text-font: ["Noto Sans Regular"]`, the glyphs OpenFreeMap serves. The MapLibre default font is not available there.
- Marker images come from `components/icons/markers.ts`; never hand-build marker images in a page.

## Charts

- ECharts through `echarts/core` with only the charts and components a screen uses registered (`components/analytics/SeriesChart.tsx`); never import the full `echarts` bundle.
- One chart instance per mount, resized by a `ResizeObserver`, options rebuilt from data in an effect; the component owns no data fetching.
- Series colours come from the brand palette in `SeriesChart.tsx`; a chart never invents colours.
- The Data Explorer state lives in the URL (`pages/project/ExplorerPage.tsx`), so a saved view is its search parameters and a link reproduces a view.

## Z-index ladder

Do not invent z-index values. Pick the layer; ties are broken by DOM order.

| Layer | z-index | Elements |
| --- | --- | --- |
| Map | 0 | Every map container gets an explicit `z-0` so its internal layers cannot paint over the app. MapLibre's stylesheet sets `position: relative` on its container, so a container that must fill its parent uses `absolute!` (Tailwind important) or an explicit height |
| In-page sticky | 10 to 30 | Sticky table headers, filter bars, mobile top bar at 30 |
| Backdrop | 40 | Sidebar drawer backdrop |
| App overlays | 50 | Sidebar drawer, dialogs, sheets, dropdowns, popovers, select menus |
| Fullscreen map | 70 | Map in fullscreen mode |
| Toasts | 100 | Always on top |

## Responsive rules

- Target viewports: phone 390 px, tablet 768 px, desktop 1440 px. The screenshot sweep (phase 3) opens every route at all three.
- The page body never scrolls horizontally. Wide content (tables, charts, code) scrolls inside its own `overflow-x-auto` container.
- Charts that become unreadable when squeezed get a minimum drawn width and scroll.
- Inputs stay 16 px on touch devices (global rule in `index.css`) so iOS does not zoom on focus.
- Safe-area insets are handled once on `body`. No per-component notch padding.

## State

- Filters and selection live in the URL (`useSearchParams`). The URL is the only state for anything a user might bookmark or share.
- Server data lives in TanStack Query. Query keys come from a `queryKeys` factory (phase 1), never inline arrays.
- Client state that must outlive a component (auth, selected project, long-running uploads) lives in a Zustand store. Do not use React Context for these.

## Forms

React Hook Form with a Zod schema per form. The schema is the single place for client validation. Mutation errors go to `form.setError("root", ...)`, field errors to the field. Every destructive action has a confirmation dialog.

## API access

A typed `fetch` wrapper in `src/api/client.ts` (phase 1) attaches the token, returns typed errors and never redirects with `window.location`. Domain modules (`src/api/devices.ts`, ...) export plain objects of functions. Types are generated from the API's OpenAPI schema.

## Components

- Use shadcn/ui components from `src/components/ui/`; generated files are excluded from ESLint and are not edited by hand except to fix a bug, noted in a comment.
- Short status and hint messages use one `Callout` component, never a hand-rolled coloured div.
- Every component that has a non-obvious shape gets a header comment saying why.
- Functional components, named exports, `type` imports separated.

## Testing

- Vitest with Testing Library for components and hooks. A test per component that has logic.
- Playwright smoke (phase 3) logs in and opens every route at the three viewports, fails on console errors and horizontal overflow.
