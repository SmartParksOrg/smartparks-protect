import { useTranslation } from "react-i18next";
import { Upload } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { OffloadUpload } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";

type Note = { name: string; reason: string };

type Outcome = {
  files: number;
  stations: Set<string>;
  skipped: Note[];
};

/**
 * "Upload SD card files" on the Offload page (Tim, 2026-10-18): the person who collected the
 * cards picks the files, one or more `.jsonl` files or zips of a card's LOG folders, and the
 * server puts each file with the station its name carries, so nobody has to find each
 * station's page. One toast says how many files went to how many stations; a second lists what
 * was skipped and why (a station the project does not have, a file uploaded before).
 */
export function CardUploadButton({
  projectId,
  variant = "default",
  className,
}: {
  projectId: string;
  variant?: "default" | "outline";
  className?: string;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutationToast({
    mutationFn: async (files: File[]) => {
      const outcome: Outcome = { files: 0, stations: new Set(), skipped: [] };
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        try {
          const result = await api.post<OffloadUpload>(
            `/api/v1/projects/${projectId}/offload-files`,
            { body },
          );
          outcome.files += result.files.length;
          for (const row of result.files) outcome.stations.add(row.device_name ?? row.device_id);
          outcome.skipped.push(...(result.skipped ?? []));
        } catch (error) {
          // the server refused the whole file: its message names each member and the reason
          outcome.skipped.push({ name: file.name, reason: (error as Error).message });
        }
      }
      if (outcome.files === 0) {
        throw new Error(
          outcome.skipped.map((s) => `${s.name}: ${s.reason}`).join("; ") ||
            t("Nothing was uploaded"),
        );
      }
      return outcome;
    },
    invalidate: [queryKeys.projectOffload(projectId), ["projects", projectId, "log-files"]],
    success: (o) =>
      t("{{files}} files for {{stations}} stations uploaded, decoding", {
        files: o.files,
        stations: o.stations.size,
      }),
    onSuccess: (o) => {
      if (o.skipped.length > 0)
        toast.warning(t("{{count}} files skipped", { count: o.skipped.length }), {
          description: o.skipped
            .slice(0, 5)
            .map((s) => `${s.name}: ${s.reason}`)
            .join("\n"),
          duration: 10_000,
        });
    },
  });
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept=".jsonl,.zip,application/zip"
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) upload.mutate(files);
          e.target.value = "";
        }}
      />
      <Button
        type="button"
        size="sm"
        variant={variant}
        className={className}
        disabled={upload.isPending}
        onClick={() => input.current?.click()}
      >
        <Upload className="size-4" />{" "}
        {upload.isPending ? t("Uploading…") : t("Upload SD card files")}
      </Button>
    </>
  );
}
