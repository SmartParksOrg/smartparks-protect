import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { ProgressBar } from "@/components/common/ProgressBar";
import { PanelRow } from "@/components/map/MapObjectPanel";
import { decodingPercent, useDecoding } from "@/hooks/useDecoding";
import { decodingLabel } from "@/lib/decoding";

/**
 * Data coming in, on the live map's entity and device panels (decision D366, Tim,
 * 2026-11-06: a card being decoded showed nowhere on the map): one row per thing the decoder
 * or the attribution job is doing for the device, with a spinner, the words and a thin bar,
 * polled every few seconds while it runs; nothing while nothing runs.
 */
export function DecodingRow({ deviceId }: { deviceId: string | null | undefined }) {
  const { t } = useTranslation();
  const items = useDecoding(deviceId ? [{ id: deviceId }] : []);
  if (items.length === 0) return null;
  return (
    <>
      {items.map((item) => {
        const percent = decodingPercent(item);
        const key =
          item.kind === "file"
            ? item.file.id
            : item.kind === "walk"
              ? item.walk.identity_id
              : item.job.id;
        return (
          <PanelRow key={key} label={t("Data coming in")}>
            <span className="flex items-start gap-1.5">
              <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-primary" />
              <span className="min-w-0">
                <span className="break-words">{decodingLabel(item, t)}</span>
                {percent !== null && <ProgressBar className="mt-1 w-full" percent={percent} />}
              </span>
            </span>
          </PanelRow>
        );
      })}
    </>
  );
}
