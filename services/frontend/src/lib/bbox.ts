/**
 * The viewport the coverage read is asked for (decision D371, Tim, 2026-11-06: every small pan
 * asked the server again): the view padded by a quarter of its width and height on each side
 * and snapped outward to a grid of that quarter, so the same answer serves until the map
 * leaves the padded box, and a pan of less than a quarter changes nothing.
 */
export function coverageBbox(
  west: number,
  south: number,
  east: number,
  north: number,
): string {
  const stepX = Math.max((east - west) / 4, 0.0001);
  const stepY = Math.max((north - south) / 4, 0.0001);
  const snap = (value: number, step: number, down: boolean) =>
    (down ? Math.floor(value / step) : Math.ceil(value / step)) * step;
  return [
    Math.max(-180, snap(west - stepX, stepX, true)),
    Math.max(-90, snap(south - stepY, stepY, true)),
    Math.min(180, snap(east + stepX, stepX, false)),
    Math.min(90, snap(north + stepY, stepY, false)),
  ]
    .map((v) => v.toFixed(5))
    .join(",");
}
