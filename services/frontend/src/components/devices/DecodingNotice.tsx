import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { Callout } from "@/components/common/Callout";
import { ProgressBar } from "@/components/common/ProgressBar";
import { Button } from "@/components/ui/button";
import type { Decoding } from "@/hooks/useDecoding";
import { useJustFinished } from "@/lib/motion";

/** Data coming in: the files and the walks over retained events the decoder is working on for
 * this device, or for the devices of this entity, with what is done and a bar, at the top of
 * the page on every tab (Tim, 2026-09-23: the Data tab showed it, but nobody looked there). A
 * station's card whose frames name the device is among the files, with the station's name
 * (decision D366). */
export function DecodingNotice({
  decoding,
  onOpen,
}: {
  decoding: Decoding[];
  /** Opens the Data tab, where the files are listed; absent while it is open. */
  onOpen?: () => void;
}) {
  const { t } = useTranslation();
  // the attribution job has its own notice above this one (AttributionProgress)
  const shown = decoding.filter((item) => item.kind !== "attribution");
  // the notice says the data is in and fades (decision D381)
  const finished = useJustFinished(shown.length > 0);
  if (shown.length === 0 && finished)
    return (
      <Callout
        kind="success"
        className="animate-out fade-out-0 fill-mode-forwards duration-1000"
      >
        {t("New data received.")}
      </Callout>
    );
  if (shown.length === 0) return null;
  return (
    <Callout kind="info">
      <div className="space-y-2">
        {shown.map((item) => {
          if (item.kind === "walk") {
            const { deviceId, deviceName, walk } = item;
            const percent =
              walk.total > 0
                ? Math.min(100, (walk.done / walk.total) * 100)
                : 0;
            const what = deviceName ?? walk.device_name ?? walk.external_id;
            return (
              <div
                key={`${deviceId}-${walk.identity_id}`}
                className="space-y-1"
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <Loader2 className="size-4 shrink-0 animate-spin" />
                  <span className="font-medium">
                    {walk.begun
                      ? t(
                          "Decoding the retained uplinks of {{what}}: {{done}} of {{total}}, {{percent}}%.",
                          {
                            what,
                            done: walk.done,
                            total: walk.total,
                            percent: Math.floor(percent),
                          },
                        )
                      : t("{{what}} is waiting for the decoder.", { what })}
                  </span>
                </div>
                {walk.begun && (
                  <ProgressBar className="max-w-md" percent={percent} />
                )}
              </div>
            );
          }
          const { deviceId, deviceName, file } = item;
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
