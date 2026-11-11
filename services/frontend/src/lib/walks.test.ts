import { act, renderHook } from "@testing-library/react";

import type { DeviceWalk } from "@/api/types";
import { followWalks, useFollowedWalks } from "@/lib/walks";

const walk = (device: string, done: number, begun = true): DeviceWalk => ({
  identity_id: `i-${device}`,
  external_id: `EUI-${device}`,
  device_id: device,
  device_name: device,
  total: 26,
  done,
  begun,
});

describe("followWalks", () => {
  it("keeps a live walk as the summary has it", () => {
    expect(followWalks([], [walk("a", 3)], ["a"])).toEqual([
      { ...walk("a", 3), finished: false },
    ]);
  });

  it("finishes a walk that left the summary at its total", () => {
    const before = followWalks([], [walk("a", 3, false)], ["a"]);
    expect(followWalks(before, [], ["a"])).toEqual([
      { ...walk("a", 26), finished: true },
    ]);
  });

  it("leaves out a device that never had a walk and the walks of others", () => {
    expect(followWalks([], [walk("b", 1)], ["a"])).toEqual([]);
  });
});

describe("useFollowedWalks", () => {
  it("follows the walks across the summary's polls", () => {
    const ids = ["a", "b"];
    const { result, rerender } = renderHook(
      ({ walks }) => useFollowedWalks(walks, ids),
      { initialProps: { walks: [walk("a", 0, false), walk("b", 4)] } },
    );
    expect(result.current.map((w) => w.finished)).toEqual([false, false]);
    act(() => rerender({ walks: [walk("a", 10)] }));
    expect(result.current.map((w) => [w.done, w.finished])).toEqual([
      [10, false],
      [26, true],
    ]);
    act(() => rerender({ walks: [] }));
    expect(result.current.every((w) => w.finished)).toBe(true);
  });
});
