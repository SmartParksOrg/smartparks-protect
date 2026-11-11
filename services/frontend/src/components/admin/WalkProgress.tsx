import { CircleCheck, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { DeviceWalk } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";
import { type FollowedWalk, useFollowedWalks } from "@/lib/walks";

/** One row per walk: the device, a bar and how far it is ("Waiting" while the decoder has
 * not taken it up, "Done" once it left the summary). */
export function WalkRows({ walks }: { walks: (DeviceWalk | FollowedWalk)[] }) {
  const { t } = useTranslation();
  return (
    <ul className="space-y-1 text-sm">
      {walks.map((w) => {
        const finished = "finished" in w && w.finished;
        const percent =
          w.total > 0 ? Math.min(100, (w.done / w.total) * 100) : 100;
        const name = w.device_name ?? w.external_id ?? w.device_id;
        return (
          <li
            key={w.identity_id}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto]"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              {finished ? (
                <CircleCheck className="size-3.5 shrink-0 text-brand-green-light" />
              ) : (
                <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
              )}
              <span className="truncate">
                <Link
                  className="underline"
                  to={`/admin/devices/${w.device_id}`}
                >
                  {name}
                </Link>
                {w.external_id && w.device_name && (
                  <span className="ml-1 font-mono text-xs text-muted-foreground">
                    {w.external_id}
                  </span>
                )}
              </span>
            </span>
            <div className="col-span-2 sm:col-span-1">
              <ProgressBar percent={w.begun ? percent : 0} />
            </div>
            <span className="text-xs text-muted-foreground tabular-nums">
              {/* a walk behind other work says so, not "0 of 25" (Tim, 2026-11-11) */}
              {finished
                ? t("Done")
                : w.begun
                  ? t("{{done}} of {{total}}", { done: w.done, total: w.total })
                  : t("Waiting")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** What the create dialogs show after the devices exist (Tim, 2026-11-11: after "Create and
 * reprocess" nothing said the decoder was at work): the decoding of their retained uplinks,
 * live from the summary the page polls, then that it is done. */
export function CreatedProgress({
  walks,
  deviceIds,
}: {
  walks: DeviceWalk[];
  deviceIds: readonly string[];
}) {
  const { t } = useTranslation();
  const rows = useFollowedWalks(walks, deviceIds);
  const busy = rows.some((w) => !w.finished);
  const total = rows.reduce((sum, w) => sum + w.total, 0);
  const done = rows.reduce((sum, w) => sum + (w.begun ? w.done : 0), 0);
  if (rows.length === 0)
    return (
      <Callout kind="success">
        {t("Created. No retained uplinks wait for the decoder.")}
      </Callout>
    );
  return (
    <div className="space-y-2">
      <Callout kind={busy ? "info" : "success"}>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
            {busy && <Loader2 className="size-4 shrink-0 animate-spin" />}
            <span>
              {busy
                ? t(
                    "Created. Decoding the retained uplinks: {{done}} of {{total}}.",
                    { done, total },
                  )
                : t(
                    "Created, and the {{count}} retained uplinks are decoded. The devices, the counts and the map show them now.",
                    { count: total },
                  )}
            </span>
          </div>
          {busy && <ProgressBar percent={total ? (done / total) * 100 : 0} />}
        </div>
      </Callout>
      <WalkRows walks={rows} />
      {busy && (
        <p className="text-xs text-muted-foreground">
          {t(
            "You can close this window; the decoder goes on in the background and the progress stays on this page.",
          )}
        </p>
      )}
    </div>
  );
}
