import { useTranslation } from "react-i18next";

import type { OffloadStation } from "@/api/types";
import { PanelRow } from "@/components/map/MapObjectPanel";
import { formatAgo, formatTime, formatDuration } from "@/lib/format";

/**
 * What an offload station's panel on the live map says about the station itself (decision
 * D350, Tim, 2026-10-21: the panel showed a tracker's rows, "last seen never" and a battery,
 * and nothing of the card, the visits or the trackers served). The rows read the station
 * card, `GET /devices/{id}/offload`: its last report of itself, the card as the decoder reads
 * it (decision D345), whether it listens, the visits, the trackers served in the last 30
 * days and the cards uploaded.
 */
export function StationRows({
  station,
  loading,
  now,
}: {
  station: OffloadStation | undefined;
  loading: boolean;
  now: number;
}) {
  const { t } = useTranslation();
  if (!station) {
    return (
      <PanelRow label={t("Offload")}>
        {loading ? t("Loading…") : t("no card read yet")}
      </PanelRow>
    );
  }
  const status = (station.state?.status ?? null) as Record<string, boolean | null> | null;
  const counters = (station.state?.counters ?? null) as Record<string, number | null> | null;
  const free = station.state?.sd_free_percent as number | null | undefined;
  const yesNo = (value: boolean | null | undefined) =>
    value == null ? t("unknown") : value ? t("yes") : t("no");
  return (
    <>
      <PanelRow label={t("Last report")} title={formatTime(station.state_time)}>
        {station.state_time ? formatAgo(station.state_time, now) : t("none yet")}
      </PanelRow>
      <PanelRow label={t("SD card")}>
        {station.card_ok === false ? (
          <span className="text-destructive">{t("absent or faulted")}</span>
        ) : station.card_ok ? (
          <>
            {t("usable")}
            {free != null ? ` · ${t("{{free}}% free", { free })}` : ""}
          </>
        ) : (
          t("unknown")
        )}
      </PanelRow>
      {station.state && (
        <PanelRow label={t("Listening")}>
          {yesNo(status?.lp0_listening)}
          {(station.state.storage_pending as number | null | undefined)
            ? ` · ${t("{{count}} writes pending", { count: station.state.storage_pending as number })}`
            : ""}
        </PanelRow>
      )}
      {counters && (
        <PanelRow label={t("Visits")}>
          {t("{{complete}} complete, {{partial}} partial", {
            complete: counters.visits_complete ?? 0,
            partial: counters.visits_partial ?? 0,
          })}
        </PanelRow>
      )}
      <PanelRow
        label={t("Trackers")}
        title={
          station.clock_behind_s
            ? t(
                "The station's clock runs at least {{behind}} behind, so the time is the newest record the frames carried.",
                { behind: formatDuration(station.clock_behind_s) },
              )
            : formatTime(station.last_reception_at)
        }
      >
        {(station.trackers ?? []).length > 0
          ? t("{{count}} served in 30 days", { count: (station.trackers ?? []).length }) +
            (station.last_reception_at
              ? `, ${t("last offload {{ago}}", { ago: formatAgo(station.last_reception_at, now) })}` +
                (station.clock_behind_s ? ` ${t("(clock behind)")}` : "")
              : "")
          : t("none served in 30 days")}
      </PanelRow>
      <PanelRow label={t("Cards")} title={formatTime(station.last_upload_at)}>
        {station.files > 0
          ? t("{{files}} files, {{frames}} frames", {
              files: station.files,
              frames: station.frames,
            }) +
            (station.last_upload_at
              ? `, ${t("uploaded {{ago}}", { ago: formatAgo(station.last_upload_at, now) })}`
              : "")
          : t("none uploaded yet")}
      </PanelRow>
    </>
  );
}
