import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";
import { Button } from "@/components/ui/button";
import type { Decoding } from "@/hooks/useDecoding";

/** Data coming in: the files the decoder is working on for this device, or for the devices of
 * this entity, with the frames done and a bar, at the top of the page on every tab (Tim,
 * 2026-09-23: the Data tab showed it, but nobody looked there). */
export function DecodingNotice({
  decoding,
  onOpen,
}: {
  decoding: Decoding[];
  /** Opens the Data tab, where the files are listed; absent while it is open. */
  onOpen?: () => void;
}) {
  const { t } = useTranslation();
  if (decoding.length === 0) return null;
  return (
    <Callout kind="info">
      <div className="space-y-2">
        {decoding.map(({ deviceId, deviceName, file }) => {
          const percent =
            file.frames_total > 0
              ? Math.min(100, (file.frames_done / file.frames_total) * 100)
              : 0;
          const what = deviceName
            ? `${deviceName}, ${file.original_filename}`
            : file.original_filename;
          return (
            <div key={`${deviceId}-${file.id}`} className="space-y-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <Loader2 className="size-4 shrink-0 animate-spin" />
                <span className="font-medium">
                  {file.status === "queued"
                    ? t("{{what}} is waiting for the decoder.", { what })
                    : file.frames_total === 0
                      ? t("Reading {{what}}.", { what })
                      : t(
                          "Decoding {{what}}: {{done}} of {{total}} frames, {{percent}}%.",
                          {
                            what,
                            done: file.frames_done,
                            total: file.frames_total,
                            percent: Math.floor(percent),
                          },
                        )}
                </span>
              </div>
              {file.status === "processing" && file.frames_total > 0 && (
                <ProgressBar className="max-w-md" percent={percent} />
              )}
            </div>
          );
        })}
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs text-muted-foreground">
            {t(
              "New data is coming in; the page refreshes when the decoder is done.",
            )}
          </p>
          {onOpen && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              onClick={onOpen}
            >
              {t("Show on the Data tab")}
            </Button>
          )}
        </div>
      </div>
    </Callout>
  );
}
