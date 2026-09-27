import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Feature } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
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

/** The lines of a feature, one list per line, whatever the shape. */
function linesOf(geometry: unknown): number[][][] {
  const g = geometry as GeoJSON.Geometry | null;
  if (!g) return [];
  if (g.type === "LineString") return [g.coordinates];
  if (g.type === "MultiLineString") return g.coordinates;
  return [];
}

/**
 * Several line features kept as one route (Tim, 2026-09-27): the roads an organisation
 * imported as separate lines, or drew one by one, are one road network to the rules and the
 * vehicle analysis. The parts stay unless they are asked to go with it.
 */
export function CombineRoutesDialog({
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
  const [removeParts, setRemoveParts] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const close = () => {
    setName("");
    setRemoveParts(false);
    setError(null);
    onClose();
  };
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const feature = await api.post<Feature>(
        `/api/v1/projects/${projectId}/features`,
        {
          body: {
            name: name.trim(),
            feature_type: "route",
            geometry: {
              type: "MultiLineString",
              coordinates: parts.flatMap((p) => linesOf(p.geometry)),
            },
            attributes: { combined_from: parts.map((p) => p.id) },
          },
        },
      );
      if (removeParts)
        for (const part of parts)
          await api.delete(`/api/v1/projects/${projectId}/features/${part.id}`);
      toast.success(t("{{name}} saved", { name: feature.name }));
      await client.invalidateQueries({
        queryKey: queryKeys.features(projectId),
      });
      close();
      onCombined();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };
  const lines = parts.reduce((n, p) => n + linesOf(p.geometry).length, 0);
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? null : close())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("Combine into one route")}</DialogTitle>
          <DialogDescription>
            {t(
              "The lines below are kept as one route, which the off-road rule and the vehicle analysis read as one road network.",
            )}
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          {parts.map((p) => p.name).join(" · ")}
          {" · "}
          {t("{{count}} lines", { count: lines })}
        </p>
        <Field label={t("Name")} htmlFor="route-name">
          <Input
            id="route-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("Roads")}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <Switch
            checked={removeParts}
            onCheckedChange={setRemoveParts}
            aria-label={t("Remove the parts")}
          />
          {t("Remove the parts once the route is saved")}
        </label>
        {error && <Callout kind="error">{error}</Callout>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={close}>
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={!name.trim() || saving || lines === 0}
            onClick={() => void save()}
          >
            {t("Save as one route")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
