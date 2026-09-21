import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import type { GeoJSONSource } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Feature } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import { geometryBounds } from "@/components/map/fit";
import { useMap } from "@/components/map/useMap";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTheme } from "@/hooks/useTheme";
import {
  ACCEPTED_EXTENSIONS,
  MAX_SHAPES,
  shapesOfFile,
  type ImportedShape,
} from "@/lib/importShapes";

/**
 * Areas, routes and sites from a file (phase 33, decisions D268 and D269): a shapefile zip,
 * KML, KMZ, GPX or GeoJSON is read in the browser, every shape is shown on a map with a
 * checkbox, a name and a type, and the kept ones are saved as features of the project one
 * request each. The file itself never leaves the browser.
 */

type FeatureType = "site" | "zone" | "geofence" | "route" | "fence";

interface Row extends ImportedShape {
  keep: boolean;
  type: FeatureType;
}

const TYPES_BY_GEOMETRY: Record<ImportedShape["featureType"], FeatureType[]> = {
  site: ["site"],
  route: ["route", "fence"],
  zone: ["zone", "geofence"],
};

function ShapesMap({ rows }: { rows: Row[] }) {
  const container = useRef<HTMLDivElement | null>(null);
  const { resolved } = useTheme();
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemapsFor(null), resolved === "dark"),
    [31.5, -24.9],
    4,
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: rows.map((r) => ({
        type: "Feature",
        geometry: r.geometry,
        properties: { keep: r.keep },
      })),
    };
    const source = map.getSource("import") as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource("import", { type: "geojson", data });
    map.addLayer({
      id: "import-fill",
      type: "fill",
      source: "import",
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "fill-color": "#90AE9B",
        "fill-opacity": ["case", ["get", "keep"], 0.35, 0.08],
      },
    });
    map.addLayer({
      id: "import-line",
      type: "line",
      source: "import",
      paint: {
        "line-color": "#52735E",
        "line-width": 2,
        "line-opacity": ["case", ["get", "keep"], 1, 0.3],
      },
    });
    map.addLayer({
      id: "import-point",
      type: "circle",
      source: "import",
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 5,
        "circle-color": "#52735E",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
        "circle-opacity": ["case", ["get", "keep"], 1, 0.3],
      },
    });
    const bounds = geometryBounds(
      rows as unknown as {
        geometry: { type: string; coordinates: unknown } | null;
      }[],
    );
    if (bounds)
      map.fitBounds(bounds, { padding: 30, duration: 0, maxZoom: 15 });
  }, [mapRef, ready, rows]);
  return <div ref={container} className="z-0 h-56 w-full rounded-md border" />;
}

export function ImportFeaturesDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>([]);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(
    null,
  );
  const reset = useCallback(() => {
    setRows([]);
    setFileName(null);
    setError(null);
    setSaving(null);
  }, []);
  const read = async (file: File) => {
    setError(null);
    try {
      const shapes = await shapesOfFile(file);
      if (shapes.length === 0) {
        setError(t("The file holds no shapes"));
        return;
      }
      setFileName(file.name);
      setRows(shapes.map((s) => ({ ...s, keep: true, type: s.featureType })));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const kept = rows.filter((r) => r.keep);
  const save = async () => {
    setSaving({ done: 0, total: kept.length });
    const failed: string[] = [];
    for (const [index, row] of kept.entries()) {
      try {
        await api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
          body: {
            name: row.name.trim() || `Shape ${index + 1}`,
            feature_type: row.type,
            geometry: row.geometry,
            attributes: { imported_from: fileName },
          },
        });
      } catch (e) {
        failed.push(
          `${row.name}: ${e instanceof Error ? e.message : String(e)}`,
        );
      }
      setSaving({ done: index + 1, total: kept.length });
    }
    await queryClient.invalidateQueries({
      queryKey: queryKeys.features(projectId),
    });
    const imported = kept.length - failed.length;
    if (failed.length === 0) {
      toast.success(t("{{count}} features imported", { count: imported }));
      reset();
      onOpenChange(false);
    } else {
      setSaving(null);
      setError(
        t("{{count}} features imported; these failed:", { count: imported }) +
          "\n" +
          failed.join("\n"),
      );
    }
  };
  const update = (id: string, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("Import features")}</DialogTitle>
          <DialogDescription>
            {t(
              "A shapefile (as a zip), KML, KMZ, GPX or GeoJSON file. Every shape is shown first; keep the ones you want, name them and choose their type. At most {{count}} shapes per file.",
              { count: MAX_SHAPES },
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <label
            className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground hover:bg-muted"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) void read(file);
            }}
          >
            <Upload className="size-4" />
            {fileName ?? t("Drop a file here or click to choose one")}
            <input
              type="file"
              className="sr-only"
              accept={ACCEPTED_EXTENSIONS.join(",")}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void read(file);
                e.target.value = "";
              }}
            />
          </label>
          {error && (
            <Callout kind="error">
              <span className="whitespace-pre-line">{error}</span>
            </Callout>
          )}
          {rows.length > 0 && (
            <>
              <ShapesMap rows={rows} />
              <div className="max-h-64 overflow-y-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="w-8 px-2 py-1">
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          aria-label={t("Keep every shape")}
                          checked={kept.length === rows.length}
                          onChange={(e) =>
                            setRows((rs) =>
                              rs.map((r) => ({ ...r, keep: e.target.checked })),
                            )
                          }
                        />
                      </th>
                      <th className="px-2 py-1">{t("Name")}</th>
                      <th className="px-2 py-1">{t("Type")}</th>
                      <th className="px-2 py-1">{t("Geometry")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id} className="border-t">
                        <td className="px-2 py-1">
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={t("Keep {{name}}", { name: row.name })}
                            checked={row.keep}
                            onChange={(e) =>
                              update(row.id, { keep: e.target.checked })
                            }
                          />
                        </td>
                        <td className="px-2 py-1">
                          <Input
                            className="h-8"
                            value={row.name}
                            onChange={(e) =>
                              update(row.id, { name: e.target.value })
                            }
                            aria-label={t("Name")}
                          />
                        </td>
                        <td className="px-2 py-1">
                          <Select
                            value={row.type}
                            onValueChange={(v) =>
                              update(row.id, { type: v as FeatureType })
                            }
                          >
                            <SelectTrigger
                              className="h-8 w-32"
                              aria-label={t("Type")}
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {TYPES_BY_GEOMETRY[row.featureType].map(
                                (type) => (
                                  <SelectItem key={type} value={type}>
                                    {type}
                                  </SelectItem>
                                ),
                              )}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="px-2 py-1 text-xs text-muted-foreground">
                          {row.geometry.type}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          {saving && (
            <span className="mr-auto self-center text-xs text-muted-foreground">
              {t("Saving {{done}} of {{total}}…", saving)}
            </span>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={kept.length === 0 || saving !== null}
            onClick={() => void save()}
          >
            {t("Import {{count}} features", { count: kept.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
