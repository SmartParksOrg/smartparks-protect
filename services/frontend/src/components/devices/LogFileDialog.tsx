import type { TFunction } from "i18next";
import { Download, RefreshCw, ScrollText } from "lucide-react";
import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { downloadFile } from "@/api/client";
import type { DeviceLogFile } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatAgo, formatTime } from "@/lib/format";
import { folderOf, kindLabel, kindOf, percentDone, sizeLabel } from "@/lib/logFiles";

/** What a station's file adds to the counts: frames a station saved again, frames of trackers
 * nobody named yet, frames of a tracker without keys, frames of a contradicting identity
 * (phase 42, decisions D321 and D327). */
function stationRows(f: DeviceLogFile, t: TFunction) {
  const a = f.attributes as {
    frames_repeated?: number;
    frames_retained?: number;
    errors?: Record<string, number>;
  };
  const rows: [string, string][] = [];
  if (a.frames_repeated) rows.push([t("Repeated by the station"), String(a.frames_repeated)]);
  if (a.frames_retained) rows.push([t("Of trackers not known yet"), String(a.frames_retained)]);
  const errors = a.errors ?? {};
  if (errors.CREDENTIALS_MISSING)
    rows.push([t("Of a tracker without keys"), String(errors.CREDENTIALS_MISSING)]);
  if (errors.PAYLOAD_DECODE_FAILED)
    rows.push([t("Did not verify"), String(errors.PAYLOAD_DECODE_FAILED)]);
  if (errors.DEVICE_IDENTITY_AMBIGUOUS)
    rows.push([t("Station names another tracker"), String(errors.DEVICE_IDENTITY_AMBIGUOUS)]);
  return rows;
}

/** The assignments the file's history moved back (decision D330): a device made today whose
 * only project membership, and only entity, now start at its first record. */
function extendedRows(f: DeviceLogFile, t: TFunction): [string, string][] {
  const a = f.attributes as {
    attribution_extended?: { device_id: string; kind: string; to: string; from: string }[];
    trackers?: Record<string, { device_id?: string | null }>;
  };
  const moved = a.attribution_extended ?? [];
  if (moved.length === 0) return [];
  const addressOf = (deviceId: string) =>
    Object.entries(a.trackers ?? {}).find(([, v]) => v.device_id === deviceId)?.[0];
  return moved.map((m) => {
    const who = addressOf(m.device_id);
    const label =
      m.kind === "project" ? t("In the project since") : t("On its entity since");
    return [who ? `${label} (${who})` : label, formatTime(m.to)];
  });
}

/**
 * One file's properties, as a file explorer opens them (Tim, 2026-10-16): the kind, size and
 * times, the decoder's progress or what the file brought, a station card's extra counts, the
 * error when it failed, and the actions: the trace, the original, decode again.
 */
export function LogFileDialog({
  file,
  canWrite,
  onClose,
  onTrace,
  onRedecode,
  redecoding,
}: {
  file: DeviceLogFile | null;
  canWrite: boolean;
  onClose: () => void;
  onTrace: (traceId: string) => void;
  onRedecode: (id: string) => void;
  redecoding: boolean;
}) {
  const { t } = useTranslation();
  const f = file;
  const percent = f ? percentDone(f) : null;
  const folder = f ? folderOf(f) : null;
  return (
    <Dialog open={f !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {f && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 break-all">
                <ScrollText className="size-4 shrink-0" /> {f.original_filename}
              </DialogTitle>
              <DialogDescription>
                {kindLabel(kindOf(f.acquisition_channel), t)}
                {folder ? `, ${folder}` : ""}, {sizeLabel(f.size_bytes)},{" "}
                {t("uploaded {{ago}}", { ago: formatAgo(f.uploaded_at) })}
                {f.ble_synced_at
                  ? t(", read from the device {{time}}", {
                      time: formatTime(f.ble_synced_at),
                    })
                  : ""}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge value={f.status} />
                <Badge variant="outline">{kindLabel(kindOf(f.acquisition_channel), t)}</Badge>
                {f.firmware_version && (
                  <Badge variant="outline">
                    {t("firmware {{version}}", { version: f.firmware_version })}
                  </Badge>
                )}
              </div>
              {f.status === "processing" && (
                <div className="space-y-1">
                  <div className="text-muted-foreground">
                    {percent === null
                      ? t("reading the file")
                      : t("{{done}} of {{total}} frames decoded, {{percent}}%", {
                          done: f.frames_done,
                          total: f.frames_total,
                          percent,
                        })}
                  </div>
                  {percent !== null && <ProgressBar percent={percent} />}
                </div>
              )}
              {f.status === "queued" && (
                <div className="text-muted-foreground">{t("waiting for the decoder")}</div>
              )}
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">{t("Frames")}</dt>
                <dd>
                  {f.frames_total}
                  {f.frames_failed > 0 && (
                    <span className="text-destructive">
                      {" "}
                      {t("({{count}} failed)", { count: f.frames_failed })}
                    </span>
                  )}
                </dd>
                <dt className="text-muted-foreground">{t("Records")}</dt>
                <dd>
                  {t("{{fresh}} new, {{known}} known through another path", {
                    fresh: f.records_new,
                    known: f.records_duplicate,
                  })}
                </dd>
                {f.period_start && f.period_end && (
                  <>
                    <dt className="text-muted-foreground">{t("Period")}</dt>
                    <dd>
                      {formatTime(f.period_start)} {t("to")} {formatTime(f.period_end)}
                    </dd>
                  </>
                )}
                {stationRows(f, t).map(([label, value]) => (
                  <Fragment key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd>{value}</dd>
                  </Fragment>
                ))}
                {extendedRows(f, t).map(([label, value]) => (
                  <Fragment key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd>
                      {value}{" "}
                      <span className="text-muted-foreground">
                        {t("(moved back for the history this file brought)")}
                      </span>
                    </dd>
                  </Fragment>
                ))}
              </dl>
              {f.error_message && (
                <Callout kind="error">
                  {f.error_code}: {f.error_message}
                </Callout>
              )}
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <div className="flex flex-wrap gap-2">
                {f.trace_id && (
                  <Button type="button" variant="outline" size="sm" onClick={() => onTrace(f.trace_id!)}>
                    {t("Trace")}
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    downloadFile(`/api/v1/log-files/${f.id}/download`, f.original_filename).catch(
                      (e: Error) => toast.error(e.message),
                    )
                  }
                >
                  <Download className="size-4" /> {t("Download the original")}
                </Button>
                {canWrite && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={f.status === "processing" || redecoding}
                    onClick={() => onRedecode(f.id)}
                  >
                    <RefreshCw className="size-4" /> {t("Decode again")}
                  </Button>
                )}
              </div>
              <Button type="button" onClick={onClose}>
                {t("Close")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
