import { useCallback } from "react";

import { api } from "@/api/client";
import type { User } from "@/api/types";
import { useAuthStore } from "@/stores/auth";

let timer: ReturnType<typeof setTimeout> | null = null;

/** Save the whole preference document a moment after the last change; the server keeps it per
 * user, so another browser sees the same choices. */
function scheduleSave(): void {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    const user = useAuthStore.getState().user;
    if (!user) return;
    void api
      .patch<User>("/api/v1/users/me", {
        body: { preferences: user.preferences },
      })
      .catch(() => {
        // the choice stays in this session; the next change tries again
      });
  }, 800);
}

/** One key of the user's interface preferences, kept on the server (`users.preferences`). The
 * value updates at once in every component that reads it and is saved shortly after. */
export function usePreference<T>(
  key: string,
  fallback: T,
): [T, (next: T) => void] {
  const stored = useAuthStore((s) => s.user?.preferences?.[key]) as
    T | undefined;
  const set = useCallback(
    (next: T) => {
      const user = useAuthStore.getState().user;
      if (!user) return;
      useAuthStore.setState({
        user: {
          ...user,
          preferences: { ...(user.preferences ?? {}), [key]: next },
        },
      });
      scheduleSave();
    },
    [key],
  );
  return [stored === undefined ? fallback : stored, set];
}
