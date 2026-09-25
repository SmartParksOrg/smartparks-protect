import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import type { AttributionJob } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";

/** Where a device's records stand after an assignment change (decision D206): the job's bar
 * while it is queued or running, the error when the last one failed, nothing otherwise. Sits
 * at the top of the device and entity pages, above the assignment cards. */
export function AttributionProgress({ active, failed }: { active: AttributionJob | null; failed: AttributionJob | null }) {
  const { t } = useTranslation();
  if (active) {
    const percent = active.records_total > 0 ? (active.records_done / active.records_total) * 100 : 0;
    return (
      <Callout kind="info">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Loader2 className="size-4 shrink-0 animate-spin" />
          <span className="font-medium">
            {active.status === "queued"
              ? t("{{total}} records are waiting to be given their project and entity.", { total: active.records_total })
              : t("Giving {{total}} records their project and entity: {{done}} done, {{percent}}%.", { total: active.records_total, done: active.records_done, percent: Math.floor(percent) })}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("This runs in the background and can take a few minutes for a long history. The lists, the map and Explore show the records as they are done; an assignment made meanwhile follows in a job of its own.")}
        </p>
        <ProgressBar className="mt-2 max-w-md" percent={percent} />
      </Callout>
    );
  }
  if (failed) {
    return (
      <Callout kind="error">
        {t("The last attribution of this device's records failed: {{message}}", { message: failed.error_message ?? failed.error_code ?? "" })}{" "}
        {t("\"Recompute attribution\" on the device page's Data tab runs it again.")}
      </Callout>
    );
  }
  return null;
}
