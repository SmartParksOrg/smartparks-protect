import { useTranslation } from "react-i18next";

import {
  subjectColor,
  subjectSummary,
  type ResultDocument,
} from "@/lib/analyses";

/** One card per subject with the figures that answer the question first (plan, section 8.7):
 * how far, how fast, how much space; the comparison period's figure beside each. */
export function SubjectCards({
  document,
  metrics,
  labels,
}: {
  document: ResultDocument;
  /** The metric keys to show, with their unit text. */
  metrics: [string, string][];
  labels: Record<string, string>;
}) {
  const { t } = useTranslation();
  const hasComparison = document.periods.some((p) => p.key === "comparison");
  const show = (v: number | null | undefined, unit: string): string => {
    if (v === null || v === undefined) return "–";
    if (unit === "%") return `${Math.round(v * 100)}%`;
    const text =
      Math.abs(v) >= 100
        ? v.toFixed(0)
        : Math.abs(v) >= 10
          ? v.toFixed(1)
          : v.toFixed(2);
    return unit ? `${text} ${unit}` : text;
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {document.subjects.map((subject) => {
        const main = subjectSummary(document, "main", subject.id);
        const before = hasComparison
          ? subjectSummary(document, "comparison", subject.id)
          : null;
        return (
          <div key={subject.id} className="rounded-md border bg-card p-3">
            <div className="mb-2 flex items-center gap-2">
              <span
                className="inline-block size-3 shrink-0 rounded-full"
                style={{ backgroundColor: subjectColor(subject.id) }}
                aria-hidden
              />
              <span className="truncate font-medium">{subject.name}</span>
              {subject.type && (
                <span className="truncate text-xs text-muted-foreground">
                  {subject.type}
                </span>
              )}
            </div>
            {main ? (
              <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
                {metrics.map(([key, unit]) => (
                  <div key={key} className="contents">
                    <dt className="truncate text-muted-foreground">
                      {labels[key] ?? key}
                    </dt>
                    <dd className="text-right tabular-nums">
                      {show(main[key], unit)}
                      {before && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          ({t("before")} {show(before[key], unit)})
                        </span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("No fixes in the period.")}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
