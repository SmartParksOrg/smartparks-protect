import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { ProjectLayerRead } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";

/** A band name as the server takes it: a letter, then letters, digits and underscores. */
const NAME = /^[a-z][a-z0-9_]{0,63}$/;

/**
 * The raster layers a project uploaded for the habitat analysis (phase 41, decision D315):
 * a GeoTIFF with a CRS, one band, as a continuous number or as classes, under a band name
 * the analysis form offers. The server reads the header at upload and refuses what the
 * worker could not use; the pixels stay in the bucket until a run reads them.
 */
export function LayersCard({
  projectId,
  canWrite,
}: {
  projectId: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const layers = useQuery({
    queryKey: queryKeys.projectLayers(projectId),
    queryFn: () =>
      api.get<ProjectLayerRead[]>(`/api/v1/projects/${projectId}/layers`),
  });
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"continuous" | "categorical">(
    "continuous",
  );
  const [file, setFile] = useState<File | null>(null);
  const invalidate = [
    queryKeys.projectLayers(projectId),
    queryKeys.analysisLayers(projectId),
  ];
  const upload = useMutationToast({
    mutationFn: async () => {
      if (!file) throw new Error(t("Choose a GeoTIFF first"));
      const body = new FormData();
      body.append("file", file, file.name);
      return api.post<ProjectLayerRead>(`/api/v1/projects/${projectId}/layers`, {
        body,
        query: { name, label: label || name, kind },
      });
    },
    invalidate,
    success: t("Layer uploaded"),
    onSuccess: () => {
      setName("");
      setLabel("");
      setFile(null);
      void client.invalidateQueries({
        queryKey: queryKeys.projectLayers(projectId),
      });
    },
  });
  const remove = useMutationToast({
    mutationFn: (id: string) =>
      api.delete(`/api/v1/projects/${projectId}/layers/${id}`),
    invalidate,
    success: t("Layer removed"),
  });
  const rows = layers.data ?? [];
  const nameOk = NAME.test(name);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4" /> {t("Raster layers")}
        </CardTitle>
        <CardDescription>
          {t(
            "GeoTIFFs the habitat selection analysis reads as covariates beside the satellite layers and the distances to the features: soil, land cover, anything a GIS holds. One band, a CRS with an EPSG code, at most 200 MB.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {layers.isPending ? t("Loading…") : t("No layer uploaded yet.")}
          </p>
        ) : (
          <ul className="divide-y rounded-md border text-sm">
            {rows.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
              >
                <span className="font-medium">{row.label}</span>
                <code className="text-xs text-muted-foreground">{row.name}</code>
                <span className="text-xs text-muted-foreground">
                  {t(
                    "{{kind}} · {{width}} × {{height}} cells of {{pixel}} m · EPSG:{{epsg}} · {{mb}} MB",
                    {
                      kind:
                        row.kind === "categorical"
                          ? t("classes")
                          : t("continuous"),
                      width: row.width,
                      height: row.height,
                      pixel: Number(row.pixel_m.toFixed(1)),
                      epsg: row.epsg,
                      mb: (row.size_bytes / 1_048_576).toFixed(1),
                    },
                  )}
                </span>
                {canWrite && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() => remove.mutate(row.id)}
                    aria-label={t("Remove the layer {{name}}", {
                      name: row.label,
                    })}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canWrite && (
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(ev) => {
              ev.preventDefault();
              upload.mutate(undefined);
            }}
          >
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="layer-name">
                {t("Band name")}
              </Label>
              <Input
                id="layer-name"
                className="h-8 w-36"
                value={name}
                placeholder="soil_clay"
                onChange={(ev) => setName(ev.target.value.trim())}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="layer-label">
                {t("Label")}
              </Label>
              <Input
                id="layer-label"
                className="h-8 w-44"
                value={label}
                placeholder={t("Clay content")}
                onChange={(ev) => setLabel(ev.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t("Kind")}</Label>
              <Select
                value={kind}
                onValueChange={(val) =>
                  setKind(val === "categorical" ? "categorical" : "continuous")
                }
              >
                <SelectTrigger className="h-8 w-36" aria-label={t("Kind")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="continuous">{t("A number")}</SelectItem>
                  <SelectItem value="categorical">{t("Classes")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs" htmlFor="layer-file">
                {t("GeoTIFF")}
              </Label>
              <Input
                id="layer-file"
                type="file"
                accept=".tif,.tiff,image/tiff"
                className="h-8 w-56"
                onChange={(ev) => setFile(ev.target.files?.[0] ?? null)}
              />
            </div>
            <Button
              type="submit"
              size="sm"
              className="h-8"
              disabled={!nameOk || !file || upload.isPending}
            >
              <Upload className="size-4" /> {t("Upload")}
            </Button>
            {name && !nameOk && (
              <p className="text-xs text-destructive">
                {t(
                  "The band name is lower-case letters, digits and underscores, starting with a letter.",
                )}
              </p>
            )}
          </form>
        )}
      </CardContent>
    </Card>
  );
}
