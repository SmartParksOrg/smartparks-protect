import { useTranslation } from "react-i18next";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { OffloadUpload } from "@/api/types";
import { UnknownStationDialog } from "@/components/network/UnknownStationDialog";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

type Note = NonNullable<OffloadUpload["skipped"]>[number];

type Outcome = {
  files: number;
  stations: Set<string>;
  /** Members left out because the station holds the same bytes already (decision D353). */
  duplicates: Note[];
  /** Members left out for any other reason: not a station file, no frame in it. */
  skipped: Note[];
  /** Stations the project does not have, named by the server (decision D343). */
  unknownStations: string[];
};

/** The names of up to five members with, for a duplicate, when its earlier copy was uploaded. */
function describe(notes: Note[], t: (key: string, options?: Record<string, unknown>) => string): string {
  return notes
    .slice(0, 5)
    .map((s) =>
      s.duplicate
        ? s.uploaded_at
          ? t("{{name}} (uploaded {{when}})", { name: s.name, when: formatTime(s.uploaded_at) })
          : s.name
        : `${s.name}: ${s.reason}`,
    )
    .join("\n");
}

/**
 * "Upload SD card files" on the Offload page (Tim, 2026-10-18): the person who collected the
 * cards picks the files, one or more `.jsonl` files or zips of a card's LOG folders, and the
 * server puts each file with the station its name carries, so nobody has to find each
 * station's page. One toast says how many files went to how many stations; a file the station
 * holds already is left out and a second toast names it with the date of the earlier upload
 * (decision D353: a card read twice is no error, and nothing is decoded twice); a third lists
 * what else was skipped and why (a station the project does not have, not a station file).
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
  // the files the person picked, kept for a second round once an unknown station exists
  const [picked, setPicked] = useState<File[]>([]);
  const [unknownStations, setUnknownStations] = useState<string[] | null>(null);
  const upload = useMutationToast({
    mutationFn: async (files: File[]) => {
      setPicked(files);
      const outcome: Outcome = {
        files: 0,
        stations: new Set(),
        duplicates: [],
        skipped: [],
        unknownStations: [],
      };
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        try {
          const result = await api.post<OffloadUpload>(
            `/api/v1/projects/${projectId}/offload-files`,
            { body },
          );
          outcome.files += result.files.length;
          for (const row of result.files)
            outcome.stations.add(row.device_name ?? row.device_id);
          for (const note of result.skipped ?? [])
            (note.duplicate ? outcome.duplicates : outcome.skipped).push(note);
          for (const eui of result.unknown_stations ?? [])
            if (!outcome.unknownStations.includes(eui))
              outcome.unknownStations.push(eui);
        } catch (error) {
          // the server refused the whole file: its message names each member and the reason
          outcome.skipped.push({
            name: file.name,
            reason: (error as Error).message,
            duplicate: false,
          });
        }
      }
      if (outcome.files > 0 || outcome.unknownStations.length > 0 || outcome.duplicates.length > 0)
        return outcome;
      throw new Error(
        outcome.skipped.map((s) => `${s.name}: ${s.reason}`).join("; ") ||
          t("Nothing was uploaded"),
      );
    },
    invalidate: [
      queryKeys.projectOffload(projectId),
      ["projects", projectId, "log-files"],
    ],
    onSuccess: (o) => {
      if (o.files > 0)
        toast.success(
          t("{{files}} files for {{stations}} stations uploaded, decoding", {
            files: o.files,
            stations: o.stations.size,
          }),
        );
      else if (o.unknownStations.length > 0)
        toast.success(t("The card is from a station this project does not have yet"));
      if (o.duplicates.length > 0)
        toast.info(
          o.files === 0 && o.unknownStations.length === 0
            ? t("Nothing new: all {{count}} files were uploaded before", {
                count: o.duplicates.length,
              })
            : t("{{count}} files were uploaded before and were left out", {
                count: o.duplicates.length,
              }),
          { description: describe(o.duplicates, t), duration: 10_000 },
        );
      // a station the project does not have: the dialog makes it and uploads again (D343)
      if (o.unknownStations.length > 0) setUnknownStations(o.unknownStations);
      if (o.skipped.length > 0 && o.unknownStations.length === 0)
        toast.warning(t("{{count}} files skipped", { count: o.skipped.length }), {
          description: describe(o.skipped, t),
          duration: 10_000,
        });
    },
  });
  return (
    <>
      <UnknownStationDialog
        projectId={projectId}
        euis={unknownStations}
        files={picked}
        onOpenChange={(open) => {
          if (!open) setUnknownStations(null);
        }}
        onUploaded={() => setPicked([])}
      />
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
