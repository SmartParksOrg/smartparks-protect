import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveNow } from "@/hooks/useNow";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useLiveNow (decision D387)", () => {
  it("ticks every second while a value is fresh and rests on the base clock otherwise", () => {
    const start = Date.now();
    const fresh = new Date(start - 20_000).toISOString();
    const { result } = renderHook(() => useLiveNow([fresh], start - 5));
    act(() => vi.advanceTimersByTime(1_000));
    expect(result.current).toBeGreaterThanOrEqual(start + 1_000);
    const old = new Date(start - 3_600_000).toISOString();
    const base = start - 7;
    const mounted = Date.now();
    const rested = renderHook(() => useLiveNow([old], base));
    act(() => vi.advanceTimersByTime(1_000));
    // the fresher of the base and its own 30 s clock, which has not ticked yet
    expect(rested.result.current).toBe(mounted);
  });
});

describe("useLiveNow at the minute mark (Tim, 2026-11-08)", () => {
  it("does not loop when the base clock lags behind the second clock", () => {
    // the panel's parent clock is up to 30 s behind: by it the fix is 45 s old, by the fresh
    // clock 65 s; the hook used to pick a different clock per answer and flip for ever, which
    // React stops with "Too many re-renders" and a white page
    const start = Date.now();
    const fix = new Date(start - 65_000).toISOString();
    const base = start - 20_000;
    const { result } = renderHook(() => useLiveNow([fix], base));
    expect(result.current).toBe(start);
    act(() => vi.advanceTimersByTime(30_000));
    expect(result.current).toBeGreaterThanOrEqual(start + 30_000);
  });
});
