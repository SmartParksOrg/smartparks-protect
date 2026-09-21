# 0029. One top bar on every screen, and a night mode that reaches the map

Date: 2026-09-12

Status: accepted

## Context

The top bar with the brand existed only below 1024 px; above that the navigation column carried the brand and the health dot (ADR 0028) floated in the corner of the content, which on a full-screen desktop had no bar to sit in. Rangers use the application at night, and every surface, chart and the base map were light only.

## Decision

One top bar on every screen size (decision D182): the landscape logo and the product name on the left, the theme switch and the health dot on the right, the menu button only where the navigation column is a drawer. Since 2026-09-21 (decision D276) the project switcher and the search sit in that bar as well, between the product name and the right-hand side: they say and change what every page is about, and a control that does that should not live at the top of a column which is hidden on a phone and collapsible on a desktop. Below the `sm` width the product name gives up its room to the project and the search shrinks to its magnifier; the navigation column keeps its collapse button and nothing else. Light, dark or system per account (decision D183): the preference `theme` with a switch that cycles, mirrored in the browser as `protect-theme` so the sign-in page and the first paint already know it (an inline script applies it before React), resolved against the device's setting for system; the `dark` class on the document keys a second set of the same colour tokens (dark green-grey surfaces, the brand green lightened as the primary) and Tailwind's `dark:` variants; MapLibre's attribution and scale boxes and the charts' text, grid and tooltip colours follow. The default base map follows the theme (decision D184): the choice "Follows the theme" is the default and draws OpenFreeMap Light by day and OpenFreeMap's Night map (the "fiord" style, a dark blue-grey; the near-black "dark" style was tried first and was too black) at night; every explicit choice, Night included, is kept as chosen.

## Alternatives considered

- Keeping the brand in the navigation column and only anchoring the dot: two layouts to keep aligned, and no place for a theme switch that reads the same everywhere.
- System only, no switch: a ranger on a bright phone at night wants dark regardless of the device.
- A browser-only theme: the choice would not follow the person to a second device or survive a cleared browser.
- Night as one more base map only: a bright map on a dark screen defeats the night mode for the page people use most at night.

## Consequences

The bar is the one place for the brand, the theme and the health signal on every page. Colours come from tokens only, twice defined; a component that hard-codes a surface colour breaks the night, so the convention forbids it and the sweep looks for light surfaces. Map marker halos stay white on both themes on purpose. A theme change restyles the live map (the layers are re-added when the style loads) and rebuilds the mini maps.
