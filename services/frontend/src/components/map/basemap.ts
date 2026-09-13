/** Base map styles (decision D37): OpenFreeMap vector tiles, no key. Satellite imagery with
 * labels comes from MapTiler (decision D141) when the server has a key; the picker hides it
 * otherwise, and a saved choice of it falls back to Light. The default choice follows the
 * theme (decision D184): Light by day, Night at night; every other choice is kept as chosen. */
export interface Basemap {
  label: string;
  style: string;
}

export const FREE_BASEMAPS = {
  auto: {
    label: "Follows the theme",
    style: "https://tiles.openfreemap.org/styles/positron",
  },
  liberty: {
    label: "Streets",
    style: "https://tiles.openfreemap.org/styles/liberty",
  },
  positron: {
    label: "Light",
    style: "https://tiles.openfreemap.org/styles/positron",
  },
  bright: {
    label: "Bright",
    style: "https://tiles.openfreemap.org/styles/bright",
  },
  // OpenFreeMap's "fiord", a dark blue-grey; its "dark" style is near black (Tim, 2026-09-13)
  dark: {
    label: "Night",
    style: "https://tiles.openfreemap.org/styles/fiord",
  },
} as const satisfies Record<string, Basemap>;

export type BasemapKey = keyof typeof FREE_BASEMAPS | "satellite";

/** MapTiler's hybrid style: high resolution imagery with labels, roads and borders. */
export function satelliteStyle(maptilerKey: string): string {
  return `https://api.maptiler.com/maps/hybrid/style.json?key=${encodeURIComponent(maptilerKey)}`;
}

/** The base maps a server offers: the free ones, plus satellite with a MapTiler key. */
export function basemapsFor(
  maptilerKey: string | null | undefined,
): Record<string, Basemap> {
  const maps: Record<string, Basemap> = { ...FREE_BASEMAPS };
  if (maptilerKey)
    maps.satellite = { label: "Satellite", style: satelliteStyle(maptilerKey) };
  return maps;
}

/** The style URL of a choice among the offered base maps, Light when the choice is not
 * offered; the default choice is Night at night and Light by day. */
export function basemapStyle(
  key: string,
  maps: Record<string, Basemap>,
  darkTheme = false,
): string {
  if (key === "auto") return (darkTheme ? FREE_BASEMAPS.dark : FREE_BASEMAPS.positron).style;
  return (maps[key] ?? FREE_BASEMAPS.positron).style;
}

const STORAGE_KEY = "protect-basemap";

export function loadBasemap(): BasemapKey {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && (value in FREE_BASEMAPS || value === "satellite"))
      return value as BasemapKey;
  } catch {
    // storage may be unavailable
  }
  return "auto";
}

export function saveBasemap(key: BasemapKey): void {
  try {
    localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // ignore
  }
}
