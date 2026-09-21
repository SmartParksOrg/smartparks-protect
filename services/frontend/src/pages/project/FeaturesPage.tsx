import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Combine, Plus, Trash2, Upload, Wand2, Wheat, Zap } from "lucide-react";
import { useCallback, useRef, useState } from "react";
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
import { CombineFeaturesDialog } from "@/components/features/CombineFeaturesDialog";
import { ImportFeaturesDialog } from "@/components/features/ImportFeaturesDialog";
import { DrawMap } from "@/components/map/DrawMap";
import { boundsOf, geometryBounds, type Bounds } from "@/components/map/fit";
import { drawKindFor } from "@/components/map/featureTools";
import {
  heldByEditor,
  shapeParts,
  type ProposedArea,
} from "@/components/map/propose";
import { readVerdict, type ReadBox } from "@/components/map/proposeBox";
import { ProposedAreas } from "@/components/map/ProposedAreas";
import { useUnionAreas } from "@/hooks/useCombineAreas";
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
  // rows ticked for combining (decision D274): only areas can make a zone between them
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [combineOpen, setCombineOpen] = useState(false);
  const [geometry, setGeometry] = useState<GeoJSON.Geometry | null>(null);
  // only areas make a zone between them; a route or a site among the ticked rows is left out
  const pickedAreas = ((features.data?.items ?? []) as Feature[]).filter(
    (f) =>
      picked.has(f.id) &&
      (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon"),
  );
  const [removing, setRemoving] = useState<Feature | null>(null);
  // propose mode (phase 33): a click asks what encloses it, a candidate goes into the editor
  const [proposing, setProposing] = useState(false);
  const [loaded, setLoaded] = useState<{ geometry: GeoJSON.Geometry } | null>(
    null,
  );
  const proposal = useProposeArea(projectId);
  const [asked, setAsked] = useState<"box" | "name">("box");
  const view = useRef<Bounds | null>(null);
  // the ground being read now, so the map can draw it and the list can say how much it is
  const [reading, setReading] = useState<ReadBox | null>(null);
  // the box under the pointer while it is dragged: its size shows as it grows
  const [preview, setPreview] = useState<ReadBox | null>(null);
  const proposeBox = useCallback(
    (box: ReadBox) => {
      if (proposal.isPending) return; // one read at a time (decision D277)
      setReading(box);
      setAsked("box");
      if (readVerdict(box).tooLarge) return;
      proposal.ask({ kind: "box", box });
    },
    [proposal],
  );
  const searchByName = (name: string) => {
    const bounds = view.current ?? around;
    if (!bounds) return;
    setReading(null);
    setAsked("name");
    proposal.ask({ kind: "name", name, bounds });
  };
  // a shape the editor cannot hold — a zone in several pieces, or one with an enclave inside
  // it — is kept as it came and saved that way (decision D274)
  const [kept, setKept] = useState<{
    geometry: GeoJSON.Geometry;
    parts: number;
    holes: number;
  } | null>(null);
  const takeShape = (geometry: GeoJSON.Geometry) => {
    setProposing(false);
    proposal.reset();
    if (heldByEditor(geometry)) {
      setKept(null);
      setLoaded({ geometry });
    } else {
      setLoaded(null);
      setKept({ geometry, ...shapeParts(geometry) });
    }
  };
  const pickCandidate = (candidate: ProposedArea) => {
    takeShape(candidate.geometry);
    if (!form.getValues("name") && candidate.named)
      form.setValue("name", candidate.name);
  };
  // several ticked areas as one zone (decision D274): the union is worked out by the API
  const union = useUnionAreas(projectId);
  const combineCandidates = (chosen: ProposedArea[]) => {
    union.mutate(
      { geometries: chosen.map((c) => c.geometry) },
      { onSuccess: (combined) => takeShape(combined.geometry) },
    );
  };
  const closeDialog = () => {
    setOpen(false);
    setProposing(false);
    setLoaded(null);
    setKept(null);
    proposal.reset();
  };
  const create = useMutationToast({
    mutationFn: (values: Values) =>
      api.post<Feature>(`/api/v1/projects/${projectId}/features`, {
        body: { ...values, geometry: kept?.geometry ?? geometry },
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
            {can("features:write") && pickedAreas.length > 1 && (
              <Button variant="outline" onClick={() => setCombineOpen(true)}>
                <Combine className="size-4" />{" "}
                {t("Combine {{count}} into one zone", {
                  count: pickedAreas.length,
                })}
              </Button>
            )}
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
          selection={
            can("features:write")
              ? {
                  selected: picked,
                  onChange: setPicked,
                  rowId: (f: Feature) => f.id,
                }
              : undefined
          }
        />
      </Page>
      <ImportFeaturesDialog
        projectId={projectId}
        open={importOpen}
        onOpenChange={setImportOpen}
      />
      <CombineFeaturesDialog
        projectId={projectId}
        parts={pickedAreas}
        open={combineOpen}
        onClose={() => setCombineOpen(false)}
        onCombined={() => setPicked(new Set())}
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
              if (!kept && !geometry) {
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
                onProposeBox={proposeBox}
                onProposePreview={setPreview}
                reading={proposal.isPending ? reading : null}
                ghosts={
                  kept
                    ? [
                        {
                          kind: "osm",
                          name: "",
                          geometry: kept.geometry,
                          area_m2: 0,
                          clipped: false,
                        },
                      ]
                    : (proposal.data?.candidates ?? [])
                }
                load={loaded}
                onView={(bounds) => {
                  view.current = bounds;
                }}
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
                    setReading(null);
                    proposal.cancel();
                  }}
                >
                  <Wand2 className="size-4" /> {t("Propose from the map")}
                </Button>
                {proposing && (
                  <ProposedAreas
                    proposal={proposal.data ?? null}
                    busy={proposal.isPending}
                    error={proposal.error?.message ?? null}
                    asked={asked}
                    reading={preview ?? reading}
                    onPick={pickCandidate}
                    onSearch={searchByName}
                    onCombine={combineCandidates}
                    onCancel={proposal.cancel}
                  />
                )}
                {kept && (
                  <p className="text-xs text-muted-foreground">
                    {kept.parts > 1
                      ? t(
                          "The areas do not touch: this zone is kept in {{count}} pieces, which the editor cannot correct by hand.",
                          { count: kept.parts },
                        )
                      : t(
                          "This zone has {{count}} enclaves inside it, which the editor cannot correct by hand. It is saved as it is.",
                          { count: kept.holes },
                        )}
                  </p>
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
