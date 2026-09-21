import { useQueryClient } from "@tanstack/react-query";
import { Combine } from "lucide-react";
import type { GeoJSONSource } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { queryKeys } from "@/api/queryKeys";
import type { Feature } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
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
import { useCombineFeatures, useUnionAreas } from "@/hooks/useCombineAreas";
import { formatArea } from "@/lib/geodesy";

/** The parts under the shape they make, so what is being kept is visible before it is. */
function CombinedMap({
  parts,
  combined,
}: {
  parts: Feature[];
  combined: GeoJSON.Geometry | null;
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
    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        ...parts
          .filter((p) => p.geometry)
          .map((p) => ({
            type: "Feature" as const,
            geometry: p.geometry as unknown as GeoJSON.Geometry,
            properties: { whole: false },
          })),
        ...(combined
          ? [
              {
                type: "Feature" as const,
                geometry: combined,
                properties: { whole: true },
              },
            ]
          : []),
      ],
    };
    const source = map.getSource("combine") as GeoJSONSource | undefined;
    if (source) {
      source.setData(data);
    } else {
      map.addSource("combine", { type: "geojson", data });
      map.addLayer({
        id: "combine-fill",
        type: "fill",
        source: "combine",
        filter: ["==", ["get", "whole"], true],
        paint: { "fill-color": "#90AE9B", "fill-opacity": 0.35 },
      });
      map.addLayer({
        id: "combine-parts",
        type: "line",
        source: "combine",
        filter: ["==", ["get", "whole"], false],
        paint: {
          "line-color": "#52735E",
          "line-width": 1,
          "line-dasharray": [2, 2],
          "line-opacity": 0.8,
        },
      });
      map.addLayer({
        id: "combine-line",
        type: "line",
        source: "combine",
        filter: ["==", ["get", "whole"], true],
        paint: { "line-color": "#52735E", "line-width": 2.5 },
      });
    }
    const bounds = geometryBounds(
      parts as unknown as {
        geometry: { type: string; coordinates: unknown } | null;
      }[],
    );
    if (bounds)
      map.fitBounds(bounds, { padding: 30, duration: 0, maxZoom: 15 });
  }, [mapRef, ready, parts, combined]);
  return <div ref={container} className="z-0 h-64 w-full rounded-md border" />;
}

/**
 * Several areas kept as one (phase 33, decision D274): four reserves beside each other are one
 * zone to the people who patrol them. The union is shown over its parts before it is saved,
 * and the parts stay unless they are asked to go with it — combining is not a way to lose
 * work. Where the parts overlap, the zone counts the ground once.
 */
export function CombineFeaturesDialog({
  projectId,
  parts,
  open,
  onClose,
  onCombined,
}: {
  projectId: string;
  parts: Feature[];
  open: boolean;
  onClose: () => void;
  onCombined: () => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [featureType, setFeatureType] = useState("zone");
  const [removeParts, setRemoveParts] = useState(false);
  const union = useUnionAreas(projectId);
  const combine = useCombineFeatures(projectId);
  const ids = parts.map((p) => p.id).join(",");
  const ask = union.mutate;
  useEffect(() => {
    if (!open || parts.length < 2) return;
    ask({ featureIds: ids.split(",") });
    // the ids are what decides the shape; the objects behind them do not change here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ids, ask]);
  const close = () => {
    setName("");
    setRemoveParts(false);
    union.reset();
    combine.reset();
    onClose();
  };
  const save = () => {
    combine.mutate(
      {
        name: name.trim(),
        feature_type: featureType,
        feature_ids: parts.map((p) => p.id),
        remove_parts: removeParts,
      },
      {
        onSuccess: (feature) => {
          toast.success(t("{{name}} saved", { name: feature.name }));
          void client.invalidateQueries({
            queryKey: queryKeys.features(projectId),
          });
          close();
          onCombined();
        },
        onError: (error: Error) => toast.error(error.message),
      },
    );
  };
  const combined = union.data ?? null;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? null : close())}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("Combine into one zone")}</DialogTitle>
          <DialogDescription>
            {t(
              "The areas below are kept as one feature, which rules and analyses read as a single zone. Ground two of them share is counted once.",
            )}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          {parts.map((p) => p.name).join(" · ")}
        </p>
        <CombinedMap parts={parts} combined={combined?.geometry ?? null} />
        {union.isPending && (
          <p className="text-xs text-muted-foreground">
            {t("Working out the combined shape…")}
          </p>
        )}
        {union.error && <Callout kind="error">{union.error.message}</Callout>}
        {combined && (
          <p className="text-xs text-muted-foreground">
            {formatArea(combined.area_m2)}
            {combined.parts > 1 &&
              ` · ${t("in {{count}} pieces that do not touch", { count: combined.parts })}`}
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("Name")} htmlFor="combine-name">
            <Input
              id="combine-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("The name of the whole area")}
            />
          </Field>
          <Field label={t("Type")} htmlFor="combine-type">
            <Select value={featureType} onValueChange={setFeatureType}>
              <SelectTrigger id="combine-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="zone">{t("zone")}</SelectItem>
                <SelectItem value="geofence">{t("geofence")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={removeParts}
            onChange={(e) => setRemoveParts(e.target.checked)}
          />
          {t("Remove the parts once the zone is saved")}
        </label>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={close}>
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={!name.trim() || !combined || combine.isPending}
            onClick={save}
          >
            <Combine className="size-4" /> {t("Combine")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
