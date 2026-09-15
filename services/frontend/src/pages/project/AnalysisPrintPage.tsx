import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AnalysisRun } from "@/api/types";
import logoLandscape from "@/assets/brand/logo-landscape.webp";
import { presentationFor } from "@/components/analysis/presentations";
import { ResultChart } from "@/components/analysis/ResultChart";
import { ResultTable } from "@/components/analysis/ResultTable";
import { RunSettings } from "@/components/analysis/RunView";
import { WarningsCallout } from "@/components/analysis/WarningsCallout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useProject } from "@/hooks/useProjects";
import { ThemeOverride, useTheme } from "@/hooks/useTheme";
import { documentOf, subjectPalette } from "@/lib/analyses";
import { formatTime } from "@/lib/format";
import { applyTheme } from "@/lib/theme";

/**
 * A run as a clean sheet for the printer (Tim, 2026-09-15, decision D208): the same cards,
 * map, charts and tables as the analysis page, without the application around them, on a
 * light background whatever the account's theme, with the project, the settings and the
 * version on the paper. "Save as PDF" calls the browser's print, which saves a PDF on every
 * platform; the route sits outside the application layout so nothing else prints.
 */
export function AnalysisPrintPage() {
  const { t } = useTranslation();
  const { projectId = "", module = "", runId = "" } = useParams();
  const navigate = useNavigate();
  const { project } = useProject(projectId);
  const theme = useTheme();
  // the paper is light: the document takes the light tokens while this page is open and the
  // account's theme comes back when it closes
  useEffect(() => {
    applyTheme("light");
    return () => applyTheme(theme.resolved);
  }, [theme.resolved]);
  const version = useQuery({
    queryKey: queryKeys.version,
    queryFn: () =>
      api.get<{ version: string; commit: string }>("/api/version", {
        anonymous: true,
      }),
    staleTime: Infinity,
  });
  const run = useQuery({
    queryKey: queryKeys.analysis(projectId, runId),
    queryFn: () =>
      api.get<AnalysisRun>(`/api/v1/projects/${projectId}/analyses/${runId}`),
  });
  const presentation = presentationFor(module, t, projectId, {
    printable: true,
  });
  const document = documentOf(run.data);
  const colors = document ? subjectPalette(document) : {};
  const labels: Record<string, string> = {
    ...presentation.labels,
    ...Object.fromEntries(
      (document?.subjects ?? []).map((s) => [s.id, s.name]),
    ),
  };
  const moduleLabel = module === "grazing" ? t("Grazing") : t("Movement");
  const back = `/projects/${projectId}/analyze/${module}?run=${runId}`;
  const main = document?.periods.find((p) => p.key === "main");
  const r = run.data;
  return (
    <ThemeOverride.Provider value="light">
      <div className="min-h-screen bg-white text-black">
        <div className="mx-auto max-w-5xl space-y-6 px-8 py-6 print:max-w-none print:space-y-4 print:px-0 print:py-0">
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            <Button type="button" onClick={() => window.print()}>
              <Printer className="size-4" /> {t("Save as PDF")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => navigate(back)}>
              <ArrowLeft className="size-4" /> {t("Back to the analysis")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t(
                "In the print dialog choose \"Save as PDF\" as the destination; landscape suits the map and the charts.",
              )}
            </span>
          </div>
          <header className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
            <div>
              <h1 className="text-2xl font-semibold">
                {r?.name ?? t("{{module}} analysis", { module: moduleLabel })}
              </h1>
              <p className="text-sm text-muted-foreground">
                {[
                  project?.name,
                  moduleLabel,
                  main
                    ? `${formatTime(main.time_from)} – ${formatTime(main.time_to)}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {document && document.subjects.length > 0 && (
                <p className="text-sm text-muted-foreground">
                  {document.subjects.map((s) => s.name).join(", ")}
                </p>
              )}
            </div>
            <img src={logoLandscape} alt="Smart Parks" className="h-12 w-auto" />
          </header>
          {run.isPending && (
            <p className="text-sm text-muted-foreground">{t("Loading…")}</p>
          )}
          {run.isError && (
            <p className="text-sm text-destructive">{run.error.message}</p>
          )}
          {r && !document && (
            <p className="text-sm text-muted-foreground">
              {t("The run has no result to print yet.")}
            </p>
          )}
          {r && document && (
            <>
              <section className="break-inside-avoid">
                <h2 className="mb-2 text-base font-medium">{t("Settings")}</h2>
                <RunSettings run={r} document={document} />
              </section>
              <WarningsCallout document={document} />
              <section className="break-inside-avoid">
                {presentation.render.summary(document, r, colors)}
              </section>
              <section className="break-inside-avoid">
                {presentation.render.map(document, r, colors)}
              </section>
              <div className="grid gap-4 md:grid-cols-2 [&>*]:min-w-0">
                {document.charts.map((chart) => (
                  <Card key={chart.key} className="break-inside-avoid">
                    <CardHeader>
                      <CardTitle>{labels[chart.key] ?? chart.key}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ResultChart
                        chart={chart}
                        labels={labels}
                        colorOf={(s) =>
                          s.subject ? (colors[s.subject] ?? null) : null
                        }
                      />
                    </CardContent>
                  </Card>
                ))}
              </div>
              {document.tables.map((table) => (
                <section key={table.key} className="space-y-2 break-inside-avoid">
                  <h2 className="text-base font-medium">
                    {labels[table.key] ?? table.key}
                  </h2>
                  <ResultTable table={table} labels={labels} />
                </section>
              ))}
              {presentation.render.after(document, r)}
            </>
          )}
          <footer className="flex flex-wrap justify-between gap-2 border-t pt-2 text-xs text-muted-foreground">
            <span>
              {t("Smart Parks Protect {{version}}", {
                version: version.data?.version ?? "",
              })}
            </span>
            <span>
              {t("Printed {{date}}", { date: formatTime(new Date().toISOString()) })}
            </span>
          </footer>
        </div>
      </div>
    </ThemeOverride.Provider>
  );
}
