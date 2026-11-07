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
    const rested = renderHook(() => useLiveNow([old], base));
    act(() => vi.advanceTimersByTime(1_000));
    expect(rested.result.current).toBe(base);
  });
});
