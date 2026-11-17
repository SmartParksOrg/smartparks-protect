import { CircleCheck, Loader2 } from "lucide-react";
import { useState } from "react";
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
 * then that it is done. The count comes from the create's own answer (decision D394), so the
 * progress shows at once; the summary the page polls fills in how far the decoder is. A walk
 * that ended before the first summary after the create came back was never seen in one, and
 * still reads as decoded, not as nothing waiting. */
export function CreatedProgress({
  walks,
  summaryAt,
  queued,
  deviceIds,
}: {
  walks: DeviceWalk[];
  /** When the summary behind `walks` was read; a change means one came after the create. */
  summaryAt: number;
  /** How many retained uplinks the create handed to the decoder. */
  queued: number;
  deviceIds: readonly string[];
}) {
  const { t } = useTranslation();
  const rows = useFollowedWalks(walks, deviceIds);
  // the summary on screen when the devices were made says nothing about their walks yet
  const [madeAt] = useState(summaryAt);
  const settled = summaryAt !== madeAt;
  const live = rows.filter((w) => !w.finished);
  const waiting = live.reduce(
    (sum, w) => sum + w.total - (w.begun ? w.done : 0),
    0,
  );
  const busy = queued > 0 && (!settled || live.length > 0);
  const total = queued;
  const done = settled ? Math.max(queued - waiting, 0) : 0;
  if (queued === 0)
    return (
      <Callout kind="success">
        {t("Created. No retained uplinks wait for the decoder.")}
      </Callout>
    );
  return (
    <div className="space-y-2">
      <Callout kind={busy ? "info" : "success"}>
        <div className="space-y-2">
          {/* no wrap: on a phone the spinner stood alone on a line above its sentence */}
          <div className="flex items-start gap-x-2 font-medium">
            {busy && (
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
            )}
            <span className="min-w-0">
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
