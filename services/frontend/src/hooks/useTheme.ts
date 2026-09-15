import { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

import { usePreference } from "@/hooks/usePreference";
import {
  applyTheme,
  isTheme,
  nextTheme,
  readStoredTheme,
  type ResolvedTheme,
  resolveTheme,
  storeTheme,
  type Theme,
} from "@/lib/theme";

const QUERY = "(prefers-color-scheme: dark)";
const subscribe = (onChange: () => void) => {
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};
const prefersDark = () => window.matchMedia(QUERY).matches;

/** A page that must read one way whatever the account prefers (the print view is light)
 * provides the theme here; every chart and map under it follows. */
export const ThemeOverride = createContext<ResolvedTheme | null>(null);

/** The theme of the signed-in account (decision D183): the preference `theme`, the browser's
 * copy as the fallback before the account is known, applied to the document as it changes. */
export function useTheme() {
  const [stored, setStored] = usePreference<Theme>("theme", readStoredTheme());
  const theme: Theme = isTheme(stored) ? stored : "system";
  const dark = useSyncExternalStore(subscribe, prefersDark, () => false);
  const override = useContext(ThemeOverride);
  const resolved = override ?? resolveTheme(theme, dark);
  useEffect(() => {
    applyTheme(resolved);
    storeTheme(theme);
  }, [resolved, theme]);
  const cycle = useCallback(() => setStored(nextTheme(theme)), [setStored, theme]);
  return { theme, resolved, setTheme: setStored, cycle };
}
