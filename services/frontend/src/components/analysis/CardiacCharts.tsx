import { useTranslation } from "react-i18next";

import { ResultChart } from "@/components/analysis/ResultChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  ResultChart as ResultChartData,
  ResultDocument,
} from "@/lib/analyses";

/** The metrics in the order the page reads them, by the name the document uses. */
const METRICS = ["heart_rate", "hrv", "activity", "temperature"] as const;
/** The three views of each metric (decision D290): the hours of the day, the parts of the
 * day, and the course over the period. */
const VIEWS = ["rhythm", "parts", "daily"] as const;

/** The cardiac charts a metric to a row, so a reader follows one metric across its three
 * views instead of reading heart rate beside temperature; restless nights close the list. */
export function CardiacCharts({
  document,
  labels,
  colors,
}: {
  document: ResultDocument;
  labels: Record<string, string>;
  colors: Record<string, string>;
}) {
  const { t } = useTranslation();
  const byKey = new Map(document.charts.map((c) => [c.key, c]));
  const card = (chart: ResultChartData) => (
    <Card key={chart.key} className="min-w-0">
      <CardHeader>
        <CardTitle className="text-sm">
          {labels[chart.key] ?? chart.key}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResultChart
          chart={chart}
          labels={labels}
          colorOf={(s) => (s.subject ? (colors[s.subject] ?? null) : null)}
        />
      </CardContent>
    </Card>
  );
  const restless = byKey.get("restless");
  return (
    <div className="space-y-4">
      {METRICS.map((metric) => {
        const charts = VIEWS.map((view) =>
          byKey.get(`${view}_${metric}`),
        ).filter((c): c is ResultChartData => Boolean(c));
        if (charts.length === 0) return null;
        return (
          <section key={metric} className="space-y-2">
            <h2 className="text-base font-medium">
              {labels[metric] ?? metric}
            </h2>
            <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
              {charts.map(card)}
            </div>
          </section>
        );
      })}
      {restless && (
        <section className="space-y-2">
          <h2 className="text-base font-medium">{t("Nights")}</h2>
          <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            {card(restless)}
          </div>
        </section>
      )}
    </div>
  );
}
