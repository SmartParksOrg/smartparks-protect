import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
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
import type { Bounds } from "@/components/map/fit";
import {
  bindBoxGestures,
  ensureBoxLayer,
  type ReadBox,
  readVerdict,
  removeBoxLayer,
  setBox,
} from "@/components/map/proposeBox";
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
import { Switch } from "@/components/ui/switch";
import { useTheme } from "@/hooks/useTheme";

/** One road as the API answers it (phase 38, decision D300). */
interface ProposedRoad {
  osm_id: number;
  name: string;
  highway: string;
  geometry: GeoJSON.Geometry;
}

interface Row extends ProposedRoad {
  keep: boolean;
}

/**
 * Roads from OpenStreetMap (phase 38, decision D300): a box dragged on a map reads the roads
 * and tracks OpenStreetMap knows there, the ways people walk on left out; every way is shown
 * with a checkbox and its name, and the kept ones are saved as route features, one each or
 * joined into one route, with the OpenStreetMap way id in their attributes. The off-road rule
 * measures from them. The same bounds as the area proposal: one read at a time, at most
 * 25 km².
 */
export function RoadsDialog({
  projectId,
  open,
  onOpenChange,
  around,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Where the map opens: the project's features, or the map's usual start. */
  around: Bounds | null;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>([]);
  const [reading, setReading] = useState<ReadBox | null>(null);
  const [preview, setPreview] = useState<ReadBox | null>(null);
  const [asOne, setAsOne] = useState(false);
  const [oneName, setOneName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(
    null,
  );
  const read = useMutation({
    mutationFn: (box: ReadBox) =>
      api.post<{ roads: ProposedRoad[]; attribution: string }>(
        `/api/v1/projects/${projectId}/features/roads`,
        { body: box },
      ),
    onSuccess: (data) => {
      setError(null);
      setRows(data.roads.map((r) => ({ ...r, keep: true })));
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const reset = () => {
    setRows([]);
    setReading(null);
    setPreview(null);
    setError(null);
    setSaving(null);
    setAsOne(false);
    setOneName("");
  };
  const kept = rows.filter((r) => r.keep);
  const verdict = reading ? readVerdict(reading) : null;
  const save = async () => {
    setSaving({ done: 0, total: asOne ? 1 : kept.length });
    const failed: string[] = [];
    if (asOne) {
      try {
        await api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
          body: {
            name: oneName.trim() || t("Roads"),
            feature_type: "route",
            geometry: {
              type: "MultiLineString",
              coordinates: kept.map(
                (r) => (r.geometry as GeoJSON.LineString).coordinates,
              ),
            },
            attributes: {
              imported_from: "openstreetmap",
              osm_ids: kept.map((r) => r.osm_id),
            },
          },
        });
      } catch (e) {
        failed.push(e instanceof Error ? e.message : String(e));
      }
      setSaving({ done: 1, total: 1 });
    } else {
      for (const [index, row] of kept.entries()) {
        try {
          await api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
            body: {
              name: row.name.trim() || `${row.highway} ${row.osm_id}`,
              feature_type: "route",
              geometry: row.geometry,
              attributes: {
                imported_from: "openstreetmap",
                osm_id: row.osm_id,
                highway: row.highway,
              },
            },
          });
        } catch (e) {
          failed.push(
            `${row.name}: ${e instanceof Error ? e.message : String(e)}`,
          );
        }
        setSaving({ done: index + 1, total: kept.length });
      }
    }
    await queryClient.invalidateQueries({
      queryKey: queryKeys.features(projectId),
    });
    const saved = (asOne ? 1 : kept.length) - failed.length;
    if (failed.length === 0) {
      toast.success(t("{{count}} routes saved", { count: saved }));
      reset();
      onOpenChange(false);
    } else {
      setSaving(null);
      setError(
        t("{{count}} routes saved; these failed:", { count: saved }) +
          "\n" +
          failed.join("\n"),
      );
    }
  };
  const update = (id: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.osm_id === id ? { ...r, ...patch } : r)));
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
          <DialogTitle>{t("Roads from OpenStreetMap")}</DialogTitle>
          <DialogDescription>
            {t(
              "Drag a box over the roads you want, or click for a box around a point. Every road and track OpenStreetMap knows there is listed; footpaths are left out. Keep the ones you want as routes, one each or as one route.",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {open && (
            <RoadsMap
              rows={rows}
              around={around}
              busy={read.isPending}
              reading={reading}
              preview={preview}
              onPreview={setPreview}
              onBox={(box) => {
                if (read.isPending) return;
                setReading(box);
                if (readVerdict(box).tooLarge) return;
                read.mutate(box);
              }}
            />
          )}
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {read.isPending
              ? t("Reading OpenStreetMap…")
              : verdict?.tooLarge
                ? t(
                    "That box is {{km2}} km²; a read takes at most {{max}} km².",
                    { km2: verdict.km2.toFixed(0), max: 25 },
                  )
                : reading && rows.length === 0 && read.isSuccess
                  ? t("No roads or tracks in that box.")
                  : rows.length > 0
                    ? t("{{count}} roads and tracks; {{kept}} kept.", {
                        count: rows.length,
                        kept: kept.length,
                      })
                    : t("Nothing read yet.")}
          </p>
          {error && (
            <Callout kind="error">
              <span className="whitespace-pre-line">{error}</span>
            </Callout>
          )}
          {rows.length > 0 && (
            <>
              <div className="max-h-56 overflow-y-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="w-8 px-2 py-1">
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          aria-label={t("Keep every road")}
                          checked={kept.length === rows.length}
                          onChange={(e) =>
                            setRows((rs) =>
                              rs.map((r) => ({ ...r, keep: e.target.checked })),
                            )
                          }
                        />
                      </th>
                      <th className="px-2 py-1">{t("Name")}</th>
                      <th className="px-2 py-1">{t("Kind")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.osm_id} className="border-t">
                        <td className="px-2 py-1">
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={t("Keep {{name}}", { name: row.name })}
                            checked={row.keep}
                            onChange={(e) =>
                              update(row.osm_id, { keep: e.target.checked })
                            }
                          />
                        </td>
                        <td className="px-2 py-1">
                          <Input
                            className="h-8"
                            value={row.name}
                            disabled={asOne}
                            onChange={(e) =>
                              update(row.osm_id, { name: e.target.value })
                            }
                            aria-label={t("Name")}
                          />
                        </td>
                        <td className="px-2 py-1 text-xs text-muted-foreground">
                          {row.highway}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <label className="flex items-center gap-2">
                  <Switch
                    checked={asOne}
                    onCheckedChange={setAsOne}
                    aria-label={t("Save as one route")}
                  />
                  {t("Save as one route")}
                </label>
                {asOne && (
                  <Input
                    className="h-8 w-56"
                    value={oneName}
                    placeholder={t("Name of the route")}
                    aria-label={t("Name of the route")}
                    onChange={(e) => setOneName(e.target.value)}
                  />
                )}
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              reset();
              onOpenChange(false);
            }}
          >
            {t("Cancel")}
          </Button>
          <Button
            disabled={kept.length === 0 || saving !== null}
            onClick={() => void save()}
          >
            {saving
              ? t("Saving {{done}} of {{total}}…", saving)
              : asOne
                ? t("Save as one route")
                : t("Save {{count}} routes", { count: kept.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The map of the dialog: the box gestures of propose mode and the roads read so far. */
function RoadsMap({
  rows,
  around,
  busy,
  reading,
  preview,
  onPreview,
  onBox,
}: {
  rows: Row[];
  around: Bounds | null;
  busy: boolean;
  reading: ReadBox | null;
  preview: ReadBox | null;
  onPreview: (box: ReadBox | null) => void;
  onBox: (box: ReadBox) => void;
}) {
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
    if (around)
      map.fitBounds(around, { padding: 30, duration: 0, maxZoom: 14 });
    ensureBoxLayer(map);
    const unbind = bindBoxGestures(map, {
      onPreview,
      onGesture: (gesture) => onBox(gesture.box),
    });
    map.getCanvas().style.cursor = "crosshair";
    return () => {
      unbind();
      removeBoxLayer(map);
    };
    // bound once per map; the handlers read the latest props through the callbacks
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapRef, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    setBox(map, preview ?? reading);
  }, [mapRef, ready, preview, reading]);
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
    const source = map.getSource("roads") as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
      return;
    }
    map.addSource("roads", { type: "geojson", data });
    map.addLayer({
      id: "roads-line",
      type: "line",
      source: "roads",
      paint: {
        "line-color": "#52735E",
        "line-width": 3,
        "line-opacity": ["case", ["get", "keep"], 1, 0.25],
      },
    });
  }, [mapRef, ready, rows]);
  return (
    <div className="relative">
      <div ref={container} className="z-0 h-64 w-full rounded-md border" />
      {busy && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-md bg-background/40">
          <span className="size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}
    </div>
  );
}
