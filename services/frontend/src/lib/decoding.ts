import { type Decoding, decodingPercent } from "@/hooks/useDecoding";

/** The words of one item, short enough for a panel. */
export function decodingLabel(
  item: Decoding,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const percent = decodingPercent(item);
  const share = percent === null ? "" : `, ${Math.floor(percent)}%`;
  if (item.kind === "walk")
    return t("Decoding retained uplinks: {{done}} of {{total}}{{share}}", {
      done: item.walk.done,
      total: item.walk.total,
      share,
    });
  if (item.kind === "attribution")
    return item.job.status === "queued"
      ? t("{{total}} records waiting for their project and entity", {
          total: item.job.records_total,
        })
      : t("Giving {{total}} records their project and entity{{share}}", {
          total: item.job.records_total,
          share,
        });
  const what = item.deviceName
    ? `${item.deviceName}, ${item.file.original_filename}`
    : item.file.original_filename;
  if (item.file.status === "queued") return t("{{what}} is waiting for the decoder", { what });
  if (item.file.frames_total === 0) return t("Reading {{what}}", { what });
  return t("Decoding {{what}}: {{done}} of {{total}} frames{{share}}", {
    what,
    done: item.file.frames_done,
    total: item.file.frames_total,
    share,
  });
}
