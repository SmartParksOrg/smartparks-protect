import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import type { AnalysisRun } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";
import { Badge } from "@/components/ui/badge";
import { formatAgo, formatTime } from "@/lib/format";
import { isActive } from "@/lib/analyses";

/** Where a run stands: queued, running with its progress, completed, failed with the error,
 * or cancelled; the page polls while the run is active. */
export function RunStatus({
  run,
  now,
  workerSilent,
}: {
  run: AnalysisRun;
  now: number;
  workerSilent?: boolean;
}) {
  const { t } = useTranslation();
  const label: Record<string, string> = {
    queued: t("Queued"),
    running: t("Running"),
    completed: t("Completed"),
    failed: t("Failed"),
    cancelled: t("Cancelled"),
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Badge
        variant={
          run.status === "completed"
            ? "default"
            : run.status === "failed"
              ? "destructive"
              : "secondary"
        }
      >
        {isActive(run.status) && (
          <Loader2 className="mr-1 size-3 animate-spin" />
        )}
        {label[run.status] ?? run.status}
      </Badge>
      <span
        className="text-muted-foreground"
        title={formatTime(run.created_at)}
      >
        {t("Started {{ago}}", { ago: formatAgo(run.created_at, now) })}
      </span>
      {isActive(run.status) && (
        // a bar rather than a number (Tim, 2026-09-18): it shows that the run moves and how
        // fast, and the step says what it is busy with (decision D249)
        <div className="basis-full space-y-1">
          <ProgressBar percent={run.progress} className="max-w-md" />
          <div className="text-xs text-muted-foreground">
            {run.progress}%
            {run.progress_step ? ` · ${run.progress_step}` : ""}
          </div>
        </div>
      )}
      {run.status === "queued" && workerSilent && (
        <Callout kind="warning" className="basis-full">
          {t(
            "The analysis worker has not reported lately; the run waits until it is back.",
          )}
        </Callout>
      )}
      {run.status === "failed" && (
        <Callout kind="error" className="basis-full">
          {run.error_message ?? run.error_code ?? t("The run failed.")}
        </Callout>
      )}
    </div>
  );
}
