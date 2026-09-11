import { describe, expect, it } from "vitest";

import { iconKeys, registry, resolveIcon } from "@/components/icons/registry";

const CATEGORIES = ["wildlife", "person", "vehicle", "infrastructure", "device", "event"];

/** The registry is data: every key must draw, through its own file, and every file must have the
 * shape `Icon` and `markers.ts` rely on (a square viewBox, `currentColor`, nothing baked in). */
describe("icon registry", () => {
  it("resolves every key to its own asset", () => {
    for (const key of iconKeys) {
      const resolved = resolveIcon(key);
      expect(resolved.key, key).toBe(key);
      expect(resolved.svg, key).toContain("<svg");
    }
  });

  it("keeps every fallback and category valid", () => {
    for (const key of iconKeys) {
      const entry = registry[key];
      expect(CATEGORIES, key).toContain(entry.category);
      expect(key.startsWith(`${entry.category}.`), key).toBe(true);
      if (entry.fallback) expect(registry[entry.fallback], `${key} -> ${entry.fallback}`).toBeDefined();
      expect(entry.license, key).toMatch(/^(MIT|Apache-2\.0)$/);
    }
  });

  it("ships normalised SVGs", () => {
    for (const key of iconKeys) {
      const { svg } = resolveIcon(key);
      const box = /viewBox="([^"]+)"/.exec(svg);
      expect(box, key).not.toBeNull();
      const [, , width, height] = box![1].split(" ").map(Number);
      expect(width, key).toBeCloseTo(height, 3);
      expect(svg, key).toContain('fill="currentColor"');
      expect(svg, key).not.toMatch(/<style|<title| class=|fill="#|fill="white"|fill="black"|opacity=/);
    }
  });

  it("falls back through the chain to a drawable icon", () => {
    expect(resolveIcon("wildlife.nothing_like_this").key).toBe("wildlife.generic");
    expect(resolveIcon(undefined).key).toBe("device.sensor");
    expect(resolveIcon("wildlife.jackal").entry.fallback).toBe("wildlife.canid");
  });
});
