/**
 * Smart Parks icon registry (architecture 24). Data references stable keys such as
 * `wildlife.rhino`; this module maps a key to an SVG asset with fallback through the hierarchy
 * (species, group, generic). Vite inlines the SVGs at build time so nothing is fetched at runtime.
 */
import registryJson from "@/assets/icons/icon-registry.json";

export interface IconEntry {
  asset: string;
  category: "wildlife" | "person" | "vehicle" | "infrastructure" | "device" | "event";
  label: string;
  source: string;
  license: string;
  fallback: string | null;
  earthranger_mapping: string | null;
  aliases: string[];
}

export const registry = registryJson as Record<string, IconEntry>;

const assets = import.meta.glob<string>("@/assets/icons/**/*.svg", { eager: true, query: "?raw", import: "default" });

function assetFor(entry: IconEntry): string | undefined {
  const match = Object.entries(assets).find(([path]) => path.endsWith(`/icons/${entry.asset}`));
  return match?.[1];
}

const categoryFallback: Record<IconEntry["category"], string> = {
  wildlife: "wildlife.generic",
  person: "person.ranger",
  vehicle: "vehicle.4x4",
  infrastructure: "infrastructure.gate",
  device: "device.sensor",
  event: "event.alert",
};

/** Resolve a key through its fallback chain to an entry that has an asset. */
export function resolveIcon(key: string | null | undefined): { key: string; entry: IconEntry; svg: string } {
  let current: string | null | undefined = key;
  const seen = new Set<string>();
  while (current && !seen.has(current)) {
    seen.add(current);
    const entry = registry[current];
    if (entry) {
      const svg = assetFor(entry);
      if (svg) return { key: current, entry, svg };
      current = entry.fallback;
      continue;
    }
    const prefix = current.split(".")[0] as IconEntry["category"];
    current = categoryFallback[prefix] ?? "device.sensor";
  }
  const entry = registry["device.sensor"];
  return { key: "device.sensor", entry, svg: assetFor(entry) ?? "" };
}

/** Marker family by category: what the object is decides the shape, colour says state (24.4). */
export function markerFamily(category: IconEntry["category"]): "entity" | "infrastructure" | "event" {
  if (category === "event") return "event";
  if (category === "infrastructure" || category === "device") return "infrastructure";
  return "entity";
}

export const iconKeys = Object.keys(registry).sort();
