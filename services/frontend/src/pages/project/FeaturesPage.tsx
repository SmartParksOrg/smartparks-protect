import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
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
import {
  basemapsFor,
  basemapStyle,
  loadBasemap,
} from "@/components/map/basemap";
import {
  createDrawSession,
  type DrawKind,
  type DrawSession,
} from "@/components/map/draw";
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
import { useMutationToast } from "@/hooks/useMutationToast";

const schema = z.object({
  name: z.string().min(1).max(200),
  feature_type: z.enum(["site", "zone", "geofence", "route"]),
});
type Values = z.infer<typeof schema>;

/** The drawing map of the New feature dialog: the shared terra-draw session (decision D139),
 * the kind following the feature type. Sites are a single point, routes a line, the rest a
 * polygon. */
function DrawMap({
  kind,
  onChange,
}: {
  kind: Values["feature_type"];
  onChange: (geometry: GeoJSON.Geometry | null) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement | null>(null);
  const { mapRef, ready } = useMap(
    container,
    basemapStyle(loadBasemap(), basemapsFor(null)),
    [31.5, -24.9],
    6,
  );
  const session = useRef<DrawSession | null>(null);
  const drawKind: DrawKind =
    kind === "site" ? "point" : kind === "route" ? "line" : "polygon";
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const s = createDrawSession(map, onChange);
    session.current = s;
    s.begin(drawKind);
    return () => {
      s.destroy();
      session.current = null;
    };
  }, [mapRef, ready, drawKind, onChange]);
  return (
    <div className="space-y-2">
      <div ref={container} className="z-0 h-72 w-full rounded-md border" />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {drawKind === "point"
            ? t("Click to place the site")
            : t(
                "Click to add vertices, click the last one again or press Enter to finish",
              )}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => session.current?.clear()}
        >
          {t("Clear")}
        </Button>
      </div>
    </div>
  );
}

export function FeaturesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const features = useQuery({
    queryKey: queryKeys.features(projectId),
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { limit: 500 },
      }),
  });
  const [open, setOpen] = useState(false);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [removing, setRemoving] = useState<Feature | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", feature_type: "geofence" },
  });
  const create = useMutationToast({
    mutationFn: (values: Values) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
        body: { ...values, geometry },
      }),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature created"),
    onSuccess: () => {
      setOpen(false);
      form.reset();
      setGeometry(null);
    },
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const remove = useMutationToast({
    mutationFn: (id: string) =>
      api.delete(`/api/v1/projects/${projectId}/features/${id}`),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature deleted"),
    onSuccess: () => setRemoving(null),
  });
  const columns: ColumnDef<Feature, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    { header: t("Type"), accessorKey: "feature_type" },
    { header: t("Geometry"), accessorFn: (f) => f.geometry?.type ?? "" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("Delete feature")}
          onClick={() => setRemoving(row.original)}
        >
          <Trash2 className="size-4" />
        </Button>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title={t("Features")}
        description={t("Sites, zones, geofences and routes drawn on the map")}
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="size-4" /> {t("New feature")}
          </Button>
        }
      />
      <Page>
        <DataTable
          columns={columns}
          data={features.data?.items}
          searchable
          isLoading={features.isPending}
          emptyMessage={t(
            "No features yet. Draw a site, zone, geofence or route with New feature.",
          )}
        />
      </Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("New feature")}</DialogTitle>
            <DialogDescription>
              {t("Draw the geometry on the map")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={form.handleSubmit((v) => {
              if (!geometry) {
                form.setError("root", { message: "Draw the geometry first" });
                return;
              }
              create.mutate(v);
            })}
            noValidate
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label={t("Name")}
                htmlFor="feature-name"
                error={form.formState.errors.name?.message}
              >
                <Input id="feature-name" {...form.register("name")} />
              </Field>
              <Field label={t("Type")} htmlFor="feature-type">
                <Select
                  value={form.watch("feature_type")}
                  onValueChange={(v) =>
                    form.setValue("feature_type", v as Values["feature_type"])
                  }
                >
                  <SelectTrigger id="feature-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="geofence">{t("geofence")}</SelectItem>
                    <SelectItem value="zone">{t("zone")}</SelectItem>
                    <SelectItem value="site">{t("site")}</SelectItem>
                    <SelectItem value="route">{t("route")}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            {open && (
              <DrawMap
                key={form.watch("feature_type")}
                kind={form.watch("feature_type")}
                onChange={setGeometry}
              />
            )}
            {form.formState.errors.root && (
              <Callout kind="error">
                {form.formState.errors.root.message}
              </Callout>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                {t("Cancel")}
              </Button>
              <Button type="submit" disabled={create.isPending}>
                {t("Save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={removing != null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("Delete feature")}
        description={`${removing?.name} is removed from the map.`}
        confirmLabel={t("Delete")}
        onConfirm={() => removing && remove.mutate(removing.id)}
        pending={remove.isPending}
      />
    </>
  );
}
