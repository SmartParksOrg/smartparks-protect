/**
 * Light, dark or system (decision D183): the account's preference `theme`, mirrored in the
 * browser so the sign-in page and the first paint already know it, resolved against the
 * device's own setting for "system".
 */
export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEMES: Theme[] = ["light", "dark", "system"];
export const STORAGE_KEY = "protect-theme";
const THEME_COLOUR = { light: "#52735E", dark: "#121917" };

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

export function resolveTheme(theme: Theme, prefersDark: boolean): ResolvedTheme {
  if (theme === "system") return prefersDark ? "dark" : "light";
  return theme;
}

/** The switch cycles light, dark, system. */
export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

export function readStoredTheme(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (isTheme(value)) return value;
  } catch {
    // storage may be unavailable
  }
  return "system";
}

export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore
  }
}

/** Put the resolved theme on the document: the `dark` class the tokens and the `dark:`
 * variants key on, the colour scheme for native controls, the browser chrome's colour. */
export function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLOUR[resolved]);
}
