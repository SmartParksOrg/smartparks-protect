import { ResultChart } from "@/components/analysis/ResultChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SPEED_RAMP } from "@/components/map/analysisLayers";
import type {
  ResultChart as ResultChartData,
  ResultDocument,
} from "@/lib/analyses";

/** The chart that gets the whole width: the speed over the period is read along its time
 * axis, and half a page squeezes a week into a smear. */
const WIDE = "speed_over_time";
/** The chart whose bars are the speed bands of the map, in the map's colours. */
const BANDS = "speed_bands";

/** The charts of a vehicle run (decision D308) in the order a vehicle manager asks: how fast
 * and against which limit, how far and how long per day, when in the day, at which speeds,
 * how often too fast. A run made before the decision shows the charts it has. */
export function VehicleCharts({
  document,
  labels,
  colors,
}: {
  document: ResultDocument;
  labels: Record<string, string>;
  colors: Record<string, string>;
}) {
  // a series names its vehicle by id; the legend says its name
  const named: Record<string, string> = {
    ...labels,
    ...Object.fromEntries(document.subjects.map((s) => [s.id, s.name])),
  };
  const one = document.subjects.length === 1 && document.periods.length === 1;
  const card = (chart: ResultChartData) => (
    <Card
      key={chart.key}
      className={chart.key === WIDE ? "min-w-0 lg:col-span-2" : "min-w-0"}
    >
      <CardHeader>
        <CardTitle>{labels[chart.key] ?? chart.key}</CardTitle>
      </CardHeader>
      <CardContent>
        <ResultChart
          chart={chart}
          labels={named}
          colorOf={(s) => (s.subject ? (colors[s.subject] ?? null) : null)}
          pointColors={chart.key === BANDS && one ? SPEED_RAMP : undefined}
          className={chart.key === WIDE ? "h-72 w-full" : undefined}
        />
      </CardContent>
    </Card>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      {document.charts.map(card)}
    </div>
  );
}
