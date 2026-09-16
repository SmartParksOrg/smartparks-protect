import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { ResultChart } from "@/components/analysis/ResultChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AREA_CARDS,
  deviceLevel,
  type Level,
  orderedSubjects,
  showFigure,
  trendFallback,
  type TrendWord,
} from "@/components/analysis/fleet";
import {
  levelOf,
  type ResultChart as ResultChartData,
  type ResultDocument,
  subjectSummary,
} from "@/lib/analyses";

/** The trend words, translated once per render. */
function trendWords(t: (key: string) => string): Record<TrendWord, string> {
  return {
    steady: t("steady"),
    rising: t("rising"),
    "over a year": t("over a year"),
  };
}

/** A figure as words: a list joined, a word (a source, a trend) through the labels, an empty
 * slope or days figure as the trend's word, the rest through `showFigure`. */
function figureText(
  main: Record<string, unknown> | null | undefined,
  key: string,
  labels: Record<string, string>,
  words: Record<TrendWord, string>,
): string {
  const fallback = trendFallback(main, key);
  if (fallback) return words[fallback];
  const value = main?.[key];
  if (Array.isArray(value)) return (value as unknown[]).map(String).join(", ");
  if (typeof value === "string") return labels[value] ?? value;
  return showFigure(value, key);
}

const LEVEL_CLASS: Record<string, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  critical: "bg-red-600",
};

/** A coloured dot for a level; nothing when the indicator has none. */
export function LevelDot({ level, title }: { level: Level; title?: string }) {
  if (!level) return null;
  return (
    <span
      className={`inline-block size-2.5 shrink-0 rounded-full ${LEVEL_CLASS[level]}`}
      title={title ?? level}
      aria-label={level}
    />
  );
}

/**
 * The fleet table (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, section 7): one row per device,
 * the worst first, a level dot beside every headline indicator; a click on a row scrolls to
 * the device's section. Shown when the run has more than one device.
 */
export function FleetTable({
  document,
  labels,
  colors,
  tableKey = "fleet",
}: {
  document: ResultDocument;
  labels: Record<string, string>;
  colors: Record<string, string>;
  /** Which document table to draw: the fleet table (the summary block) or the details
   * table under the map (decision D234); both hold a row per device with level dots. */
  tableKey?: "fleet" | "details";
}) {
  const { t } = useTranslation();
  const words = trendWords(t);
  const fleet = document.tables.find((x) => x.key === tableKey);
  if (!fleet) return null;
  const columns = fleet.columns.slice(2);
  const rows = orderedSubjects(document).map((subject) => ({
    subject,
    main: subjectSummary(document, "main", subject.id) as Record<
      string,
      unknown
    > | null,
  }));
  const goTo = (id: string) =>
    globalThis.document
      .getElementById(`device-${id}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {tableKey === "details" ? t("Details per device") : t("Fleet")}
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3 font-medium">{t("Device")}</th>
              <th className="py-1 pr-3 font-medium">{t("Level")}</th>
              {columns.map((c) => (
                <th key={c} className="py-1 pr-3 font-medium whitespace-nowrap">
                  {labels[c] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ subject, main }) => (
              <tr
                key={subject.id}
                className="cursor-pointer border-t hover:bg-muted/40"
                onClick={() => goTo(subject.id)}
              >
                <td className="py-1 pr-3 whitespace-nowrap">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="inline-block size-2.5 rounded-full"
                      style={{ backgroundColor: colors[subject.id] }}
                      aria-hidden
                    />
                    {subject.name}
                    {subject.tracked && (
                      <span className="text-xs text-muted-foreground">
                        {subject.tracked}
                      </span>
                    )}
                  </span>
                </td>
                <td className="py-1 pr-3">
                  <LevelDot level={deviceLevel(document, subject.id)} />
                </td>
                {columns.map((c) => (
                  <td
                    key={c}
                    className="py-1 pr-3 tabular-nums whitespace-nowrap"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <LevelDot
                        level={levelOf(document, subject.id, c)}
                        title={`${labels[c] ?? c}: ${levelOf(document, subject.id, c)}`}
                      />
                      {figureText(main, c, labels, words)}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/**
 * One section per device: the four area cards with the figures and their levels, the
 * comparison beside each when the run has one, and the device's own charts. Folded when the
 * run has several devices, open for a single one.
 */
export function DeviceSections({
  document,
  labels,
  colors,
}: {
  document: ResultDocument;
  labels: Record<string, string>;
  colors: Record<string, string>;
}) {
  const { t } = useTranslation();
  const words = trendWords(t);
  const hasComparison = document.periods.some((p) => p.key === "comparison");
  const single = document.subjects.length === 1;
  // the subjects' names label their series
  const named: Record<string, string> = {
    ...labels,
    ...Object.fromEntries(document.subjects.map((s) => [s.id, s.name])),
  };
  const shown = (value: unknown): boolean =>
    value !== undefined &&
    value !== null &&
    !(Array.isArray(value) && value.length === 0);
  return (
    <div className="space-y-3">
      {orderedSubjects(document).map((subject) => {
        const main = subjectSummary(document, "main", subject.id) as Record<
          string,
          unknown
        > | null;
        const before = hasComparison
          ? (subjectSummary(document, "comparison", subject.id) as Record<
              string,
              unknown
            > | null)
          : null;
        const charts: ResultChartData[] = document.charts
          .map((chart) => ({
            ...chart,
            series: chart.series.filter((s) => s.subject === subject.id),
          }))
          .filter((chart) => chart.series.length > 0);
        return (
          <details
            key={subject.id}
            id={`device-${subject.id}`}
            open={single}
            className="rounded-md border bg-card"
          >
            <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 font-medium">
              <span
                className="inline-block size-3 rounded-full"
                style={{ backgroundColor: colors[subject.id] }}
                aria-hidden
              />
              {subject.name}
              <LevelDot level={deviceLevel(document, subject.id)} />
              {subject.type && (
                <span className="text-xs font-normal text-muted-foreground">
                  {subject.type}
                </span>
              )}
              {subject.tracked && (
                <span className="text-xs font-normal text-muted-foreground">
                  {t("tracked {{name}}", { name: subject.tracked })}
                </span>
              )}
            </summary>
            <div className="space-y-3 px-3 pb-3">
              {main ? (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {AREA_CARDS.map(([area, keys]) => {
                    const present = keys.filter(
                      (k) => shown(main[k]) || trendFallback(main, k) !== null,
                    );
                    if (present.length === 0) return null;
                    return (
                      <div key={area} className="rounded-md border p-3">
                        <p className="mb-2 text-sm font-medium">
                          {labels[area] ?? area}
                        </p>
                        <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-sm">
                          {present.map((key) => (
                            <div key={key} className="contents">
                              <dt className="flex items-start gap-1.5 leading-tight text-muted-foreground">
                                <span className="mt-1.5 inline-flex shrink-0">
                                  <LevelDot
                                    level={levelOf(document, subject.id, key)}
                                  />
                                </span>
                                <span>{labels[key] ?? key}</span>
                              </dt>
                              <dd className="flex flex-col items-end text-right tabular-nums leading-tight">
                                <span>
                                  {figureText(main, key, labels, words)}
                                </span>
                                {before && shown(before[key]) && (
                                  <span className="text-xs text-muted-foreground">
                                    {t("before")} {showFigure(before[key], key)}
                                  </span>
                                )}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("Nothing in the period.")}
                </p>
              )}
              {charts.length > 0 && (
                <div className="grid gap-3 lg:grid-cols-2 [&>*]:min-w-0">
                  {charts.map((chart) => (
                    <Card key={chart.key}>
                      <CardHeader>
                        <CardTitle>{labels[chart.key] ?? chart.key}</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ResultChart
                          chart={chart}
                          labels={named}
                          colorOf={(s) =>
                            s.subject ? (colors[s.subject] ?? null) : null
                          }
                        />
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}

/** The defaults behind the levels, named, so a reader sees what "warn" meant. */
export function LevelDefaults({
  document,
  labels,
}: {
  document: ResultDocument;
  labels: Record<string, string>;
}): ReactNode {
  const { t } = useTranslation();
  const defaults = document.summary.defaults as
    Record<string, string> | undefined;
  if (!defaults) return null;
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("The thresholds behind the levels")}
      </summary>
      <p className="mt-2 text-muted-foreground">
        {t(
          "A driver's own thresholds come first (the OpenCollar battery and temperature bounds, say); where a driver declares none, these defaults apply.",
        )}
      </p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-muted-foreground">
        {Object.entries(defaults).map(([key, text]) => (
          <div key={key} className="contents">
            <dt>{labels[key] ?? key}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
