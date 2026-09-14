import { useTranslation } from "react-i18next";

import { pressureColor } from "@/components/map/analysisLayers";
import type { ResultDocument } from "@/lib/analyses";

/** The grazing and rest calendar (plan, section 9.4): one row per area, one cell per day of
 * the main period, filled by that day's animal-hours against the area's busiest day; an
 * empty cell is a rest day. Drawn from the timeline chart's series, so it needs no extra
 * data. */
export function RestStrip({
  document,
  restThreshold,
}: {
  document: ResultDocument;
  restThreshold: number;
}) {
  const { t } = useTranslation();
  const timeline = document.charts.find((c) => c.key === "timeline");
  const series = (timeline?.series ?? []).filter(
    (s) => s.period === "main" && !("herd" in s && s.herd !== "A"),
  );
  if (series.length === 0) return null;
  const days = series[0].data.map((d) => Number(d[0]));
  const fmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
  return (
    <div className="space-y-2 overflow-x-auto">
      <h2 className="text-base font-medium">{t("Use and rest by day")}</h2>
      <table className="text-xs">
        <thead>
          <tr>
            <th className="pr-2 text-left font-normal text-muted-foreground">
              {t("Area")}
            </th>
            {days.map((ms, i) => (
              <th
                key={ms}
                className="w-3 p-0 text-left font-normal text-muted-foreground"
                title={fmt.format(new Date(ms))}
              >
                {i % 7 === 0 ? (
                  <span className="block w-0 -rotate-90 whitespace-nowrap">
                    {fmt.format(new Date(ms))}
                  </span>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((s) => {
            const max = Math.max(...s.data.map((d) => Number(d[1] ?? 0)), 0);
            return (
              <tr key={s.area ?? s.name}>
                <td className="whitespace-nowrap pr-2">{s.name}</td>
                {s.data.map((d) => {
                  const hours = Number(d[1] ?? 0);
                  const rest = hours <= restThreshold;
                  return (
                    <td key={String(d[0])} className="p-0">
                      <span
                        className="block size-3 border border-background"
                        title={`${fmt.format(new Date(Number(d[0])))}: ${hours.toFixed(1)} ${t("animal-hours")}`}
                        style={{
                          backgroundColor: rest
                            ? "transparent"
                            : pressureColor(max > 0 ? (hours / max) * 2 : 0),
                          outline: rest ? "1px solid var(--border)" : undefined,
                          outlineOffset: "-1px",
                        }}
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">
        {t("An empty cell is a rest day; the darker the cell, the more animal-hours against the area's busiest day.")}
      </p>
    </div>
  );
}
