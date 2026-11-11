import { useState } from "react";

import type { DeviceWalk } from "@/api/types";

/** A walk over a device's retained events as the dialog that started it follows it: the walk
 * as the summary has it, or, once it left the summary, the walk as last seen and finished. */
export interface FollowedWalk extends DeviceWalk {
  finished: boolean;
}

/** The walks of `deviceIds` after a new summary: a live walk as it stands, a walk seen before
 * and gone now finished at its total, a device never seen with a walk left out. */
export function followWalks(
  before: FollowedWalk[],
  walks: DeviceWalk[],
  deviceIds: readonly string[],
): FollowedWalk[] {
  const out: FollowedWalk[] = [];
  for (const id of deviceIds) {
    const live = walks.find((w) => w.device_id === id);
    const seen = before.find((w) => w.device_id === id);
    if (live) out.push({ ...live, finished: false });
    else if (seen)
      out.push({ ...seen, done: seen.total, begun: true, finished: true });
  }
  return out;
}

/** `followWalks` kept across the summary's polls, adjusted during render. */
export function useFollowedWalks(
  walks: DeviceWalk[],
  deviceIds: readonly string[],
): FollowedWalk[] {
  const key = JSON.stringify([walks, deviceIds]);
  const [state, setState] = useState<{ key: string; rows: FollowedWalk[] }>(
    () => ({ key, rows: followWalks([], walks, deviceIds) }),
  );
  if (state.key !== key)
    setState({ key, rows: followWalks(state.rows, walks, deviceIds) });
  return state.rows;
}
