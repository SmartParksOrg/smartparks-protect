import { useSearchParams } from "react-router";

const HALF_WINDOW_MS = 12 * 3600_000;

/** `?at=<time>` on the Data tab (phase 19): a track point on the map links here, so the
 * positions list shows the records around that moment instead of the latest ones, and the row
 * at that time is highlighted. */
export function useAt(): {
  at: string | null;
  from: string | null;
  to: string | null;
  isAt: (time: string) => boolean;
  clear: () => void;
} {
  const [params, setParams] = useSearchParams();
  const raw = params.get("at");
  const ms = raw ? Date.parse(raw) : NaN;
  const at = Number.isFinite(ms) ? new Date(ms).toISOString() : null;
  return {
    at,
    from: at ? new Date(ms - HALF_WINDOW_MS).toISOString() : null,
    to: at ? new Date(ms + HALF_WINDOW_MS).toISOString() : null,
    isAt: (time: string) => at !== null && Date.parse(time) === ms,
    clear: () =>
      setParams(
        (p) => {
          p.delete("at");
          return p;
        },
        { replace: true },
      ),
  };
}
