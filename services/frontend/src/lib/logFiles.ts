/** Pure helpers of the log files explorer (phase 42, Tim, 2026-10-16: one line per file, as a
 * file explorer shows them, with a tile view beside it). */
import type { TFunction } from "i18next";

import type { DeviceLogFile } from "@/api/types";
import { t as mark } from "@/lib/i18nMark";

export type LogFileKind = "raw_log" | "browser_sync" | "station_card" | "other";

const KIND_OF_CHANNEL: Record<string, LogFileKind> = {
  log_file: "raw_log",
  webble: "browser_sync",
  lp0: "station_card",
};

const KIND_LABEL: Record<LogFileKind, string> = {
  raw_log: mark("raw log"),
  browser_sync: mark("browser sync"),
  station_card: mark("SD card"),
  other: mark("file"),
};

export function kindOf(channel: string): LogFileKind {
  return KIND_OF_CHANNEL[channel] ?? "other";
}

export function kindLabel(kind: LogFileKind, t: TFunction): string {
  return t(KIND_LABEL[kind]);
}

/** The card folder a station's file came from (`LOG_3`), when the file knows it. */
export function folderOf(file: DeviceLogFile): string | null {
  const folder = (file.attributes as { folder?: unknown }).folder;
  return typeof folder === "string" && folder ? folder : null;
}

/** How far the decoder is with a processing file, 0 to 100; null before the file is read. */
export function percentDone(file: DeviceLogFile): number | null {
  if (file.frames_total === 0) return null;
  return Math.min(100, Math.floor((file.frames_done / file.frames_total) * 100));
}

/** "12 kB", "1.3 MB": the size as a file explorer prints it. */
export function sizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} kB`;
}

/** The one line under a file's name: where the decoder is, or what the file brought. */
export function summaryOf(file: DeviceLogFile, t: TFunction): string {
  if (file.status === "queued") return t("waiting for the decoder");
  if (file.status === "processing") {
    const percent = percentDone(file);
    return percent === null
      ? t("reading the file")
      : t("{{done}} of {{total}} frames decoded, {{percent}}%", {
          done: file.frames_done,
          total: file.frames_total,
          percent,
        });
  }
  if (file.status === "failed" && file.error_message) return file.error_message;
  const parts = [
    t("{{count}} frames", { count: file.frames_total }),
    t("{{count}} new records", { count: file.records_new }),
  ];
  if (file.records_duplicate > 0)
    parts.push(t("{{count}} known", { count: file.records_duplicate }));
  if (file.frames_failed > 0) parts.push(t("{{count}} failed", { count: file.frames_failed }));
  return parts.join(", ");
}
