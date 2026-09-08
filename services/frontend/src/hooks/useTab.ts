import { useSearchParams } from "react-router";

/** The page's tab from `?tab=` (decision D133), the first one when absent or unknown, so a
 * link can land on a tab; changing it replaces the history entry. */
export function useTab<T extends string>(
  tabs: readonly T[],
): [T, (tab: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab = (tabs as readonly string[]).includes(raw ?? "")
    ? (raw as T)
    : tabs[0];
  const setTab = (next: T) =>
    setParams(
      (p) => {
        if (next === tabs[0]) p.delete("tab");
        else p.set("tab", next);
        return p;
      },
      { replace: true },
    );
  return [tab, setTab];
}
