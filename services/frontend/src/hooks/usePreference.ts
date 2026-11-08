import { useCallback } from "react";

import { api } from "@/api/client";
import type { User } from "@/api/types";
import { prunePreferences, withRecentScope } from "@/lib/preferences";
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
    // the document stays under the server's bound (decision D392): the scopes visited least
    // recently let go of their layer choices, map view and feed mark
    const preferences = prunePreferences(user.preferences ?? {});
    if (preferences !== user.preferences)
      useAuthStore.setState({ user: { ...user, preferences } });
    void api
      .patch<User>("/api/v1/users/me", { body: { preferences } })
      .catch((error: unknown) => {
        // the choice stays in this session; the next change tries again
        console.warn("Preferences not saved", error);
      });
  }, 800);
}

/** Marks `scope` (a project id or "all") as the one in use, so its choices are the last to
 * go when the document is trimmed (decision D392). Called when the live map opens a scope. */
export function rememberScope(scope: string): void {
  const user = useAuthStore.getState().user;
  if (!user) return;
  const preferences = withRecentScope(user.preferences ?? {}, scope);
  if (preferences === user.preferences) return;
  useAuthStore.setState({ user: { ...user, preferences } });
  scheduleSave();
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
