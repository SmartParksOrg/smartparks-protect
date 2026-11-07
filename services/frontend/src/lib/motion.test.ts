import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  easeOut,
  prefersReducedMotion,
  useCountUp,
  useDelayed,
  useJustChanged,
  useJustFinished,
  useReducedMotion,
} from "@/lib/motion";

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

describe("useJustFinished", () => {
  it("is true for a while after busy fell, never on the first render", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ busy }) => useJustFinished(busy, 500),
      {
        initialProps: { busy: false },
      },
    );
    expect(result.current).toBe(false);
    rerender({ busy: true });
    expect(result.current).toBe(false);
    rerender({ busy: false });
    expect(result.current).toBe(true);
    act(() => vi.advanceTimersByTime(500));
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});

describe("useCountUp", () => {
  it("counts from zero to the value and ticks to the next one", () => {
    let now = 0;
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("performance", { now: () => now });
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) =>
      frames.push(cb),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const { result, rerender } = renderHook(
      ({ value }) => useCountUp(value, 400),
      {
        initialProps: { value: 100 as number | null },
      },
    );
    expect(result.current).toBe(0);
    now = 200;
    act(() => frames.shift()?.(now));
    expect(result.current).toBeGreaterThan(50);
    expect(result.current).toBeLessThan(100);
    now = 400;
    act(() => frames.shift()?.(now));
    expect(result.current).toBe(100);
    rerender({ value: 120 });
    now = 800;
    act(() => frames.shift()?.(now));
    expect(result.current).toBe(120);
  });
  it("shows the value at once under reduce motion", () => {
    fakeMatchMedia(true);
    const { result } = renderHook(() => useCountUp(42));
    expect(result.current).toBe(42);
  });
  it("passes null through", () => {
    const { result } = renderHook(() => useCountUp(null));
    expect(result.current).toBeNull();
  });
});

describe("easeOut", () => {
  it("starts at zero, ends at one, is fast at first", () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(0.5)).toBeGreaterThan(0.5);
    expect(easeOut(2)).toBe(1);
  });
});

describe("useDelayed", () => {
  it("is true only once the flag held for the delay, and drops at once", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ flag }) => useDelayed(flag, 300),
      {
        initialProps: { flag: true },
      },
    );
    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(300));
    expect(result.current).toBe(true);
    rerender({ flag: false });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});

describe("useJustChanged", () => {
  it("is true for a while after the value changed, never on the first render", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ value }) => useJustChanged(value, 500),
      {
        initialProps: { value: "ok" },
      },
    );
    expect(result.current).toBe(false);
    rerender({ value: "degraded" });
    expect(result.current).toBe(true);
    act(() => vi.advanceTimersByTime(500));
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});
