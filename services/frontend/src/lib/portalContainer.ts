/** Where a floating menu, list or popover should be rendered.
 *
 * These portal to `document.body` by default, and a browser showing an element full screen
 * paints only that element and what is inside it: a menu opened from a full-screen map lands in
 * the body, outside the painted subtree, so it opens invisibly (Tim, 2026-09-18: the base map
 * selector did nothing in full screen). Putting it inside the full-screen element instead keeps
 * it visible, and with nothing full screen this is `undefined`, which leaves the default alone.
 */
export function portalContainer(): HTMLElement | undefined {
  if (typeof document === "undefined") return undefined;
  return (document.fullscreenElement as HTMLElement | null) ?? undefined;
}
