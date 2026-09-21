import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2, Upload, Wand2, Wheat, Zap } from "lucide-react";
import { useCallback, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CurrentState, Feature, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { ImportFeaturesDialog } from "@/components/features/ImportFeaturesDialog";
import { DrawMap } from "@/components/map/DrawMap";
import { boundsOf, geometryBounds } from "@/components/map/fit";
import { drawKindFor } from "@/components/map/featureTools";
import type { ProposedArea } from "@/components/map/propose";
import { ProposedAreas } from "@/components/map/ProposedAreas";
import { useProposeArea } from "@/hooks/useProposeArea";
import { Button } from "@/components/ui/button";
import { useAnalysisModules, usePermissions } from "@/hooks/useProjects";
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
  feature_type: z.enum(["site", "zone", "geofence", "route", "fence"]),
});
type Values = z.infer<typeof schema>;

export function FeaturesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const { can } = usePermissions(projectId);
  const features = useQuery({
    queryKey: queryKeys.features(projectId),
    queryFn: () =>
      api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, {
        query: { limit: 500 },
      }),
  });
  const navigate = useNavigate();
  // where a new drawing starts: over what the project already has drawn, else over its
  // entities and devices, else the map's usual start (Tim, 2026-09-19)
  const current = useQuery({
    queryKey: queryKeys.currentState(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`),
  });
  const around =
    geometryBounds(
      (features.data?.items ?? []) as unknown as {
        geometry: { type: string; coordinates: unknown } | null;
      }[],
    ) ??
    boundsOf(
      (current.data?.features as unknown as
        | { geometry: { type: string; coordinates: unknown } | null }[]
        | undefined) ?? [],
    );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", feature_type: "geofence" },
  });
  const [open, setOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [removing, setRemoving] = useState<Feature | null>(null);
  // propose mode (phase 33): a click asks what encloses it, a candidate goes into the editor
  const [proposing, setProposing] = useState(false);
  const [loaded, setLoaded] = useState<{ geometry: GeoJSON.Geometry } | null>(
    null,
  );
  const proposal = useProposeArea(projectId);
  const proposeAt = useCallback(
    (lonLat: [number, number]) => proposal.mutate(lonLat),
    [proposal],
  );
  const pickCandidate = (candidate: ProposedArea) => {
    setLoaded({ geometry: candidate.geometry });
    setProposing(false);
    proposal.reset();
    if (!form.getValues("name") && candidate.named)
      form.setValue("name", candidate.name);
  };
  const closeDialog = () => {
    setOpen(false);
    setProposing(false);
    setLoaded(null);
    proposal.reset();
  };
  const create = useMutationToast({
    mutationFn: (values: Values) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
        body: { ...values, geometry },
      }),
    invalidate: [queryKeys.features(projectId)],
    success: t("Feature created"),
    onSuccess: (created) => {
      closeDialog();
      form.reset();
      setGeometry(null);
      // a fence line has a setup of its own: the thresholds and the monitors on it
      if (created.feature_type === "fence")
        navigate(`/projects/${projectId}/features/${created.id}/fence`);
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
  const analysisModules = useAnalysisModules(projectId);
  const grazingOn = analysisModules.includes("grazing") && can("analysis:run");
  const columns: ColumnDef<Feature, unknown>[] = [
    { header: t("Name"), accessorKey: "name" },
    { header: t("Type"), accessorKey: "feature_type" },
    { header: t("Geometry"), accessorFn: (f) => f.geometry?.type ?? "" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="flex items-center justify-end gap-1">
          {row.original.feature_type === "fence" && (
            <Button
              asChild
              variant="ghost"
              size="icon"
              aria-label={t("Fence line")}
              title={t("Fence line")}
            >
              <Link
                to={`/projects/${projectId}/features/${row.original.id}/fence`}
              >
                <Zap className="size-4" />
              </Link>
            </Button>
          )}
          {grazingOn &&
            ["zone", "geofence"].includes(row.original.feature_type) && (
              <Button
                asChild
                variant="ghost"
                size="icon"
                aria-label={t("Grazing in this area")}
                title={t("Grazing in this area")}
              >
                <Link
                  to={`/projects/${projectId}/analyze/grazing?area=${row.original.id}`}
                >
                  <Wheat className="size-4" />
                </Link>
              </Button>
            )}
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("Delete feature")}
            onClick={() => setRemoving(row.original)}
          >
            <Trash2 className="size-4" />
          </Button>
        </span>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title={t("Features")}
        description={t("Sites, zones, geofences and routes drawn on the map")}
        actions={
          <>
            {can("features:write") && (
              <Button variant="outline" onClick={() => setImportOpen(true)}>
                <Upload className="size-4" /> {t("Import")}
              </Button>
            )}
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" /> {t("New feature")}
            </Button>
          </>
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
      <ImportFeaturesDialog
        projectId={projectId}
        open={importOpen}
        onOpenChange={setImportOpen}
      />
      <Dialog
        open={open}
        onOpenChange={(o) => (o ? setOpen(true) : closeDialog())}
      >
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
                form.setError("root", {
                  message: t("Draw the geometry first"),
                });
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
                    <SelectItem value="fence">{t("fence")}</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            {open && (
              <DrawMap
                key={form.watch("feature_type")}
                kind={drawKindFor(form.watch("feature_type"))}
                around={around}
                onChange={setGeometry}
                proposing={proposing}
                onProposeAt={proposeAt}
                ghosts={proposal.data?.candidates ?? []}
                load={loaded}
              />
            )}
            {drawKindFor(form.watch("feature_type")) === "polygon" && (
              <div className="space-y-2">
                <Button
                  type="button"
                  variant={proposing ? "default" : "outline"}
                  size="sm"
                  aria-pressed={proposing}
                  onClick={() => {
                    setProposing((p) => !p);
                    proposal.reset();
                  }}
                >
                  <Wand2 className="size-4" /> {t("Propose from the map")}
                </Button>
                {proposing && (
                  <ProposedAreas
                    proposal={proposal.data ?? null}
                    busy={proposal.isPending}
                    error={proposal.error?.message ?? null}
                    onPick={pickCandidate}
                  />
                )}
              </div>
            )}
            {form.formState.errors.root && (
              <Callout kind="error">
                {form.formState.errors.root.message}
              </Callout>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={closeDialog}>
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
