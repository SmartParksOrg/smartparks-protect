import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import * as maplibregl from "maplibre-gl";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Feature, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { loadBasemap } from "@/components/map/basemap";
import { useMap } from "@/components/map/useMap";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";

const schema = z.object({ name: z.string().min(1).max(200), feature_type: z.enum(["site", "zone", "geofence", "route"]) });
type Values = z.infer<typeof schema>;

/** Click on the map to add vertices, finish with the button. Sites are a single point. */
function DrawMap({ kind, onChange }: { kind: Values["feature_type"]; onChange: (geometry: GeoJSON.Geometry | null) => void }) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready } = useMap(container, loadBasemap(), [31.5, -24.9], 6);
  const [points, setPoints] = useState<[number, number][]>([]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const onClick = (e: maplibregl.MapMouseEvent) => setPoints((p) => (kind === "site" ? [[e.lngLat.lng, e.lngLat.lat]] : [...p, [e.lngLat.lng, e.lngLat.lat]]));
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
    };
  }, [mapRef, ready, kind]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let geometry: GeoJSON.Geometry | null = null;
    if (kind === "site" && points.length === 1) geometry = { type: "Point", coordinates: points[0] };
    else if (kind === "route" && points.length >= 2) geometry = { type: "LineString", coordinates: points };
    else if (kind !== "site" && kind !== "route" && points.length >= 3) geometry = { type: "Polygon", coordinates: [[...points, points[0]]] };
    onChange(geometry);
    const data: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [...points.map((c) => ({ type: "Feature" as const, geometry: { type: "Point" as const, coordinates: c }, properties: {} })), ...(geometry && geometry.type !== "Point" ? [{ type: "Feature" as const, geometry, properties: {} }] : [])] };
    const source = map.getSource("draw") as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(data);
    else {
      map.addSource("draw", { type: "geojson", data });
      map.addLayer({ id: "draw-fill", type: "fill", source: "draw", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#90AE9B", "fill-opacity": 0.3 } });
      map.addLayer({ id: "draw-line", type: "line", source: "draw", filter: ["!=", ["geometry-type"], "Point"], paint: { "line-color": "#52735E", "line-width": 2 } });
      map.addLayer({ id: "draw-points", type: "circle", source: "draw", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 5, "circle-color": "#52735E", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    }
  }, [mapRef, ready, points, kind, onChange]);
  return (
    <div className="space-y-2">
      <div ref={container} className="z-0 h-72 w-full rounded-md border" />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{kind === "site" ? "Click to place the site" : kind === "route" ? `${points.length} points, click to add` : `${points.length} vertices, at least 3 for a polygon`}</span>
        <Button type="button" variant="ghost" size="sm" onClick={() => setPoints([])}>{t("Clear")}</Button>
      </div>
    </div>
  );
}

export function FeaturesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const features = useQuery({ queryKey: queryKeys.features(projectId), queryFn: () => api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, { query: { limit: 500 } }) });
  const [open, setOpen] = useState(false);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [removing, setRemoving] = useState<Feature | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", feature_type: "geofence" } });
  const create = useMutationToast({
    mutationFn: (values: Values) => api.post<Feature>(`/api/v1/projects/${projectId}/features`, { body: { ...values, geometry } }),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature created"),
    onSuccess: () => { setOpen(false); form.reset(); setGeometry(null); },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const remove = useMutationToast({ mutationFn: (id: string) => api.delete(`/api/v1/projects/${projectId}/features/${id}`), invalidate: [queryKeys.features(projectId)], success: t("Feature deleted"), onSuccess: () => setRemoving(null) });
  const columns: ColumnDef<Feature, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    { header: t("Type"), accessorKey: "feature_type" },
    { header: t("Geometry"), accessorFn: (f) => f.geometry?.type ?? "" },
    { id: "actions", header: "", cell: ({ row }) => <Button variant="ghost" size="icon" aria-label={t("Delete feature")} onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button> },
  ];
  return (
    <>
      <PageHeader title={t("Features")} description={t("Sites, zones, geofences and routes drawn on the map")} actions={<Button onClick={() => setOpen(true)}><Plus className="size-4" /> {t("New feature")}</Button>} />
      <Page><DataTable columns={columns} data={features.data?.items} isLoading={features.isPending} emptyMessage={t("No features yet.")} /></Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader><DialogTitle>{t("New feature")}</DialogTitle><DialogDescription>{t("Draw the geometry on the map")}</DialogDescription></DialogHeader>
          <form className="space-y-4" onSubmit={form.handleSubmit((v) => { if (!geometry) { form.setError("root", { message: "Draw the geometry first" }); return; } create.mutate(v); })} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Name")} htmlFor="feature-name" error={form.formState.errors.name?.message}><Input id="feature-name" {...form.register("name")} /></Field>
              <Field label={t("Type")} htmlFor="feature-type">
                <Select value={form.watch("feature_type")} onValueChange={(v) => form.setValue("feature_type", v as Values["feature_type"])}>
                  <SelectTrigger id="feature-type"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="geofence">{t("geofence")}</SelectItem><SelectItem value="zone">{t("zone")}</SelectItem><SelectItem value="site">{t("site")}</SelectItem><SelectItem value="route">{t("route")}</SelectItem></SelectContent>
                </Select>
              </Field>
            </div>
            {open && <DrawMap key={form.watch("feature_type")} kind={form.watch("feature_type")} onChange={setGeometry} />}
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={create.isPending}>{t("Save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing != null} onOpenChange={(o) => !o && setRemoving(null)} title={t("Delete feature")} description={`${removing?.name} is removed from the map.`} confirmLabel={t("Delete")} onConfirm={() => removing && remove.mutate(removing.id)} pending={remove.isPending} />
    </>
  );
}
