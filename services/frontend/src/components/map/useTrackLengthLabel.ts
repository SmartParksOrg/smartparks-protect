import { useTranslation } from "react-i18next";

import { describeHours, type TrackLength } from "@/components/map/trackLength";

/** "21 days", "6 hours" or "since assignment" for the Tracks card and the tooltips. */
export function useTrackLengthLabel(length: TrackLength): string {
  const { t } = useTranslation();
  if (length === "assigned") return t("since assignment");
  const { value, unit } = describeHours(length);
  return unit === "days"
    ? t("{{count}} days", { count: value })
    : t("{{count}} hours", { count: value });
}
