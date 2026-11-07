# 0042. Motion that explains, never decorates

Date: 2026-11-07

Status: accepted; builds on 0029

## Context

Protect's interface had almost no motion: dialogs and menus appeared at once, a marker jumped to its new fix, charts drew in one frame, panels popped into place. Tim asked on 2026-11-07 whether animations could make the interface feel more modern and alive. The frontend has every piece for it already: Tailwind 4 with the theme tokens, Radix overlays that expose their open and closed state, MapLibre with its own camera easing, ECharts with transitions built in, and a WebSocket that tells the page when something is new. The shadcn overlays even carried their animation classes since phase 3, but the package defining those classes was never added, so the classes did nothing.

Motion costs attention, battery and WebGL time on a field tablet, and some people cannot follow a moving screen. Without a rule, animation grows into decoration: bouncing, shimmering, routes that slide, markers that pulse all day.

## Decision

Every animation in Protect says one of three things: the element came from somewhere, it changed, or it is working. Nothing moves to look pleasant.

- Durations: 150 to 300 ms for the interface (an overlay, a panel, a badge, a tab's content), 600 ms for a marker gliding to its new fix, up to 800 ms for the map camera as before. The constants are `DURATION` in `lib/motion.ts`.
- Direction: an element enters from the edge it belongs to; an overlay scales from 95 %. No bouncing or elastic easing.
- Colour: the brand green is the only colour that pulses (the ring of a new fix, the flash of a finished decode).
- The map: nothing animates while nothing is new. A ring or a glide follows a position from the WebSocket, never a refetch or a page load, and no frame is drawn while no marker is on its way.
- Reads: no shimmer or placeholder animation for a read under 300 ms; a loading bar when nobody knows how long it takes, a progress bar when the share is known.
- Off switch: the operating system's reduce-motion setting turns every animation off, in CSS through one rule in `index.css`, on the map and in the charts through `useReducedMotion`. Protect has no switch of its own.

## Alternatives considered

- A motion library (Framer Motion, React Spring): more than the rules need; Tailwind's utilities, `tw-animate-css`, `requestAnimationFrame` and ECharts' transitions cover every case here without another runtime.
- An Animations switch in the preferences beside the theme: a second place to turn motion off, which the operating system already offers, and one more setting to explain.
- Continuous life on the map (a breathing marker, a scanning ring per gateway): draws frames all day on a field tablet and says nothing new.

## Consequences

Overlays, panels and tabs animate as designed; the live map shows which marker just reported; charts draw in and morph; summary numbers count to their value. Every new component takes its duration from `DURATION` and its off switch from the reduce-motion rule, so a review can ask of any animation which of the three things it says. The CSS rule ends spinners and loading bars under reduce motion too; a static icon in their place is the accepted practice.
