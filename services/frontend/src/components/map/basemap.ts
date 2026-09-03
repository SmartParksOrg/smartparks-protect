/** Base map styles (decision D37): OpenFreeMap vector tiles, no key. Satellite comes later behind an optional key. */
export const BASEMAPS = {
  liberty: { label: "Streets", style: "https://tiles.openfreemap.org/styles/liberty" },
  positron: { label: "Light", style: "https://tiles.openfreemap.org/styles/positron" },
  bright: { label: "Bright", style: "https://tiles.openfreemap.org/styles/bright" },
} as const;

export type BasemapKey = keyof typeof BASEMAPS;

const STORAGE_KEY = "protect-basemap";

export function loadBasemap(): BasemapKey {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && value in BASEMAPS) return value as BasemapKey;
  } catch {
    // storage may be unavailable
  }
  return "positron";
}

export function saveBasemap(key: BasemapKey): void {
  try {
    localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // ignore
  }
}
