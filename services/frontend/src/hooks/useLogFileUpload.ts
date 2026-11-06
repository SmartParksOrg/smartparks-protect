import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, OffloadUpload } from "@/api/types";
import { useMutationToast } from "@/hooks/useMutationToast";

/** A station's card: one JSONL file of the card, or a zip of its LOG folders (phase 42). */
export function isStationUpload(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".jsonl") || name.endsWith(".zip");
}

/** What the input offers: raw logs as the OpenCollar BLE app exports them, and a station's card. */
export const LOG_FILE_ACCEPT = ".txt,.log,.jsonl,.zip,text/plain,application/zip";

/**
 * The upload of a device's files (decision D367): a raw log, one frame per line as the BLE
 * app exports it, goes to the raw log route; a station's card to the offload route, where a
 * zip becomes one row per file. Several files go one after another. The device page's card,
 * the header of the device and entity pages and the Devices list share it.
 */
export function useLogFileUpload(deviceId: string) {
  const { t } = useTranslation();
  const upload = useMutationToast({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      if (isStationUpload(file)) {
        const result = await api.post<OffloadUpload>(`/api/v1/devices/${deviceId}/offload-files`, {
          body,
        });
        const notes = result.skipped ?? [];
        return {
          name: file.name,
          files: result.files.length,
          // the station holds these bytes already: left out, named, no error (decision D353)
          duplicates: notes.filter((s) => s.duplicate).length,
          skipped: notes.filter((s) => !s.duplicate).length,
        };
      }
      const row = await api.post<DeviceLogFile>(`/api/v1/devices/${deviceId}/log-files`, { body });
      return { name: row.original_filename, files: 1, duplicates: 0, skipped: 0 };
    },
    invalidate: [
      queryKeys.logFiles(deviceId),
      queryKeys.offloadStation(deviceId),
      queryKeys.decoding(deviceId),
    ],
    onSuccess: (r) => {
      if (r.files === 0 && r.duplicates > 0 && r.skipped === 0)
        toast.info(
          t("Nothing new: all {{count}} files of {{name}} were uploaded before", {
            count: r.duplicates,
            name: r.name,
          }),
        );
      else if (r.files === 1 && r.duplicates === 0 && r.skipped === 0)
        toast.success(`${r.name} uploaded, decoding`);
      else
        toast.success(t("{{name}}: {{files}} files uploaded, {{skipped}} skipped, decoding", r));
      if (r.duplicates > 0 && r.files > 0)
        toast.info(t("{{count}} files were uploaded before and were left out", { count: r.duplicates }));
    },
    onError: (error) =>
      toast.error(
        error.message.includes("uploaded before")
          ? t("This file was uploaded before for this device.")
          : error.message,
      ),
  });
  /** Every chosen file, one after another, so the toasts and the rows arrive in order. */
  const uploadAll = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      try {
        await upload.mutateAsync(file);
      } catch {
        // the toast said what went wrong; the next file still goes
      }
    }
  };
  return { upload, uploadAll, isPending: upload.isPending };
}
