import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { prefersReducedMotion, useReducedMotion } from "@/lib/motion";

type Listener = () => void;

function fakeMatchMedia(matches: boolean) {
  const listeners = new Set<Listener>();
  const media = {
    matches,
    addEventListener: (_: string, listener: Listener) =>
      listeners.add(listener),
    removeEventListener: (_: string, listener: Listener) =>
      listeners.delete(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  return {
    set(value: boolean) {
      media.matches = value;
      listeners.forEach((listener) => listener());
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("prefersReducedMotion", () => {
  it("is false where the browser cannot say", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(prefersReducedMotion()).toBe(false);
  });
  it("reads the setting", () => {
    fakeMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
  });
});

describe("useReducedMotion", () => {
  it("follows the setting while it changes", () => {
    const media = fakeMatchMedia(false);
    const { result, rerender } = renderHook(() => useReducedMotion());
    expect(result.current).toBe(false);
    media.set(true);
    rerender();
    expect(result.current).toBe(true);
  });
});
