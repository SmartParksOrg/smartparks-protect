/**
 * Marker images for MapLibre. Each registry icon is rendered onto a canvas with the marker family
 * shape (round for entities, square for infrastructure and devices, diamond for events) and a
 * state colour ring, then registered with `map.addImage`. Colour communicates state; the
 * silhouette communicates type (architecture 24.4).
 */
import type { Map as MapLibreMap } from "maplibre-gl";

import { markerFamily, resolveIcon } from "@/components/icons/registry";

export type MarkerState =
  "normal" | "warning" | "critical" | "offline" | "selected";

const STATE_COLOURS: Record<MarkerState, string> = {
  normal: "#52735E",
  warning: "#C6B187",
  critical: "#A13D2D",
  offline: "#8A9590",
  // a blue no state uses, with a halo behind the marker, so the selected one stands out
  // from every other at a glance (Tim, 2026-09-21: the darker green was not enough)
  selected: "#2563EB",
};

const SELECTED_HALO = "rgba(37, 99, 235, 0.28)";

export function markerImageId(iconKey: string, state: MarkerState): string {
  return `marker:${iconKey}:${state}`;
}

async function svgToImage(
  svg: string,
  colour: string,
  size: number,
): Promise<HTMLImageElement> {
  const coloured = svg.replace(/currentColor/g, colour);
  const image = new Image(size, size);
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(coloured)}`;
  await image.decode();
  return image;
}

export async function ensureMarkerImage(
  map: MapLibreMap,
  iconKey: string,
  state: MarkerState,
): Promise<string> {
  const id = markerImageId(iconKey, state);
  if (map.hasImage(id)) return id;
  const { svg, entry } = resolveIcon(iconKey);
  const family = markerFamily(entry.category);
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return id;
  const colour = STATE_COLOURS[state];
  if (state === "selected") {
    // the halo fills the image; the marker itself is drawn smaller inside it
    ctx.fillStyle = SELECTED_HALO;
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.translate(size / 2, size / 2);
    ctx.scale(0.8, 0.8);
    ctx.translate(-size / 2, -size / 2);
  }
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = colour;
  ctx.lineWidth = state === "selected" ? 7 : 5;
  ctx.beginPath();
  if (family === "entity") {
    ctx.arc(size / 2, size / 2, size / 2 - 4, 0, Math.PI * 2);
  } else if (family === "infrastructure") {
    ctx.roundRect(4, 4, size - 8, size - 8, 10);
  } else {
    ctx.moveTo(size / 2, 3);
    ctx.lineTo(size - 3, size / 2);
    ctx.lineTo(size / 2, size - 3);
    ctx.lineTo(3, size / 2);
    ctx.closePath();
  }
  ctx.fill();
  ctx.stroke();
  const icon = await svgToImage(svg, colour, size);
  const inset = family === "event" ? 18 : 14;
  ctx.drawImage(icon, inset, inset, size - inset * 2, size - inset * 2);
  if (!map.hasImage(id))
    map.addImage(id, ctx.getImageData(0, 0, size, size), { pixelRatio: 2 });
  return id;
}
