import { useTranslation } from "react-i18next";

import { pressureColor } from "@/components/map/analysisLayers";
import { type ResultDocument, subjectSummary } from "@/lib/analyses";

interface AreaInfo {
  id: string;
  name: string;
  kind: string;
  hectares: number;
}

/** One card per area with the figures that answer the question (plan, section 9.4): use per
 * hectare, the relative pressure with its rank, use and rest days, the last use; the herd's
 * share inside the areas above them. */
export function AreaCards({
  document,
  labels,
}: {
  document: ResultDocument;
  labels: Record<string, string>;
}) {
  const { t } = useTranslation();
  const areas = (document.summary.areas as AreaInfo[] | undefined) ?? [];
  const herd = (document.summary.herd as Record<string, Record<string, number>>)
    ?.main;
  const weighting = document.summary.weighting as { unit?: string } | undefined;
  const hasComparison = document.periods.some((p) => p.key === "comparison");
  const num = (v: number | null | undefined, digits = 2): string =>
    v === null || v === undefined ? "–" : v.toFixed(digits);
  return (
    <div className="space-y-3">
      {herd && (
        <p className="text-sm text-muted-foreground">
          {t(
            "The herd was tracked for {{hours}} animal-hours; {{inside}}% of that time inside the chosen areas, {{outside}}% outside.",
            {
              hours: Math.round(herd.tracked_animal_hours),
              inside: Math.round(herd.share_inside * 100),
              outside: Math.round(herd.share_outside * 100),
            },
          )}{" "}
          {weighting?.unit && weighting.unit !== "animals" && (
            <span>{t("Weighted in {{unit}}.", { unit: weighting.unit })}</span>
          )}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {areas.map((area) => {
          const main = subjectSummary(document, "main", area.id);
          const before = hasComparison
            ? subjectSummary(document, "comparison", area.id)
            : null;
          const pressure = main?.relative_pressure ?? null;
          return (
            <div key={area.id} className="rounded-md border bg-card p-3">
              <div className="mb-2 flex items-center gap-2">
                <span
                  className="inline-block size-3 shrink-0 rounded-sm"
                  style={{ backgroundColor: pressureColor(pressure) }}
                  aria-hidden
                />
                <span className="truncate font-medium">{area.name}</span>
                <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                  {t("{{value}} ha", { value: num(area.hectares, 1) })}
                </span>
              </div>
              {main ? (
                <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
                  <dt className="text-muted-foreground">
                    {labels.animal_days_per_ha}
                  </dt>
                  <dd className="text-right tabular-nums">
                    {num(main.animal_days_per_ha, 3)}
                    {before && (
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({t("before")} {num(before.animal_days_per_ha, 3)})
                      </span>
                    )}
                  </dd>
                  <dt className="text-muted-foreground">
                    {labels.relative_pressure}
                  </dt>
                  <dd className="text-right tabular-nums">
                    {num(pressure)}
                    {pressure !== null &&
                      main.pressure_rank !== null &&
                      main.pressure_rank !== undefined &&
                      ` (#${main.pressure_rank})`}
                  </dd>
                  <dt className="text-muted-foreground">
                    {labels.animals_used}
                  </dt>
                  <dd className="text-right tabular-nums">
                    {num(main.animals_used, 0)}
                  </dd>
                  <dt className="text-muted-foreground">{labels.use_days}</dt>
                  <dd className="text-right tabular-nums">
                    {num(main.use_days, 0)} / {num(main.rest_days, 0)}{" "}
                    {t("rest")}
                  </dd>
                  <dt className="text-muted-foreground">
                    {labels.longest_rest_days}
                  </dt>
                  <dd className="text-right tabular-nums">
                    {num(main.longest_rest_days, 0)}
                  </dd>
                  <dt className="text-muted-foreground">
                    {labels.hours_since_last_use}
                  </dt>
                  <dd className="text-right tabular-nums">
                    {num(main.hours_since_last_use, 0)}
                  </dd>
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("Not used.")}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
