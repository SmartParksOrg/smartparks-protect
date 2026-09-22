import { useTranslation } from "react-i18next";

import type { ResultDocument } from "@/lib/analyses";

interface Coverage {
  heard?: number;
  with_reading?: number;
  expected?: number | null;
  reading_share?: number | null;
  heard_share?: number | null;
  longest_gap_hours?: number | null;
}

interface Figures {
  coverage?: Coverage;
  heart_rate?: { median?: number; p10?: number; p90?: number; n?: number };
  resting_heart_rate?: number;
  resting_readings?: number;
  hrv?: { median?: number };
  tag_temperature?: { median?: number };
  temperature_difference?: number;
  dropped_implausible?: number;
}

/** A card per subject: what the collar heard first, then what the heart was doing.
 *
 * The order is the point. A heart rate chart cannot tell a quiet tag from a calm animal, so the
 * coverage line stands above the figures rather than under them, and a subject the collar barely
 * heard says so before it says a number. */
export function CardiacSummary({ document }: { document: ResultDocument }) {
  const { t } = useTranslation();
  const summary = document.summary as {
    subjects?: Record<string, Figures>;
    settings?: {
      quiet_hours?: number[];
      resting_quantile?: number;
    };
  };
  const per = summary.subjects ?? {};
  const settings = summary.settings ?? {};
  const quiet = settings.quiet_hours ?? [];
  const hour = (value: number) => `${String(value).padStart(2, "0")}:00`;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {document.subjects.map((subject) => {
          const figures = per[subject.id] ?? {};
          const seen = figures.coverage ?? {};
          const rate = figures.heart_rate ?? {};
          const lines: [string, string][] = [
            [
              t("Heard"),
              seen.expected
                ? t("{{heard}} of about {{expected}} times", {
                    heard: seen.heard ?? 0,
                    expected: seen.expected,
                  })
                : t("{{heard}} times", { heard: seen.heard ?? 0 }),
            ],
            [
              t("With a cardiac reading"),
              seen.reading_share != null
                ? `${Math.round(seen.reading_share * 100)}%`
                : t("none"),
            ],
            [
              t("Median heart rate"),
              rate.median != null ? `${rate.median} bpm` : t("no readings"),
            ],
            [
              t("Resting heart rate"),
              figures.resting_heart_rate != null
                ? `${figures.resting_heart_rate} bpm`
                : t("too few quiet readings"),
            ],
            [
              t("Usual range"),
              rate.p10 != null && rate.p90 != null
                ? `${rate.p10} to ${rate.p90} bpm`
                : "–",
            ],
            [
              t("Median HRV"),
              figures.hrv?.median != null
                ? `${figures.hrv.median} ms`
                : t("not sent by this firmware"),
            ],
            [
              t("Tag temperature"),
              figures.tag_temperature?.median != null
                ? `${figures.tag_temperature.median} °C`
                : "–",
            ],
            [
              t("Longest silence"),
              seen.longest_gap_hours != null
                ? t("{{hours}} hours", { hours: seen.longest_gap_hours })
                : "–",
            ],
          ];
          return (
            <div key={subject.id} className="min-w-0 rounded-md border p-3">
              <p className="truncate text-sm font-medium">{subject.name}</p>
              <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm">
                {lines.map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          );
        })}
      </div>
      {quiet.length === 2 && (
        <p className="text-xs text-muted-foreground">
          {t(
            "Resting is the {{quantile}} quantile of the readings taken between {{from}} and {{to}}, on the project's clock.",
            {
              quantile: settings.resting_quantile ?? 0.1,
              from: hour(quiet[0]),
              to: hour(quiet[1]),
            },
          )}
        </p>
      )}
    </div>
  );
}
