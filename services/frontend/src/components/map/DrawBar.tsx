import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { Circle, MapPin, Minus, Pentagon, X } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import type { DrawKind, DrawState } from "@/components/map/draw";
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
import { featureTypesFor } from "@/components/map/featureTools";
import { formatArea, formatLength, measure } from "@/lib/geodesy";

/**
 * The bar of the draw and measure modes (decisions D139, D141, D171): what to draw, the length,
 * area or radius of the shape while it is drawn and after, and the way out: Save as feature for
 * a drawing, Done for a measurement, which is kept nowhere.
 */
export function DrawBar({
  purpose,
  kind,
  state,
  onKind,
  onSave,
  onCancel,
}: {
  purpose: "draw" | "measure";
  kind: DrawKind;
  state: DrawState;
  onKind: (kind: DrawKind) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const { geometry, live, circle } = state;
  const m = measure(live);
  // nothing to show before the pointer moved (a circle's first tap has no radius yet)
  const measured = (m.length_m ?? 0) > 0 || (m.area_m2 ?? 0) > 0 || circle;
  const kinds: { kind: DrawKind; label: string; icon: typeof MapPin }[] = [
    { kind: "point", label: t("Point"), icon: MapPin },
    { kind: "line", label: t("Line"), icon: Minus },
    { kind: "polygon", label: t("Polygon"), icon: Pentagon },
    { kind: "circle", label: t("Circle"), icon: Circle },
  ];
  return (
    <div className="rounded-md border bg-card p-2 text-sm shadow-md">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">
          {purpose === "draw" ? t("Draw") : t("Measure")}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={t("Cancel")}
          onClick={onCancel}
        >
          <X className="size-4" />
        </Button>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {kinds
          .filter((k) => purpose === "draw" || k.kind !== "point")
          .map(({ kind: k, label, icon: Icon }) => (
            <Button
              key={k}
              variant={kind === k ? "default" : "outline"}
              size="sm"
              className="h-8"
              aria-pressed={kind === k}
              onClick={() => onKind(k)}
            >
              <Icon className="size-4" /> {label}
            </Button>
          ))}
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {geometry === null
          ? kind === "point"
            ? t("Tap the map to place the point.")
            : kind === "circle"
              ? t(
                  "Tap the centre, then tap again at the radius; Escape cancels.",
                )
              : t(
                  "Tap the map to add vertices, tap the last one again or press Enter to finish, Escape to cancel.",
                )
          : kind === "circle"
            ? t("Drag the circle to move it; Escape clears.")
            : t(
                "Drag a vertex to move it, a midpoint to add one; Escape clears.",
              )}
      </div>
      {measured && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {circle && (
            <span>
              <span className="text-muted-foreground">{t("Radius")} </span>
              <span className="font-medium">{formatLength(circle.radius_m)}</span>
            </span>
          )}
          {m.area_m2 != null && (
            <span>
              <span className="text-muted-foreground">{t("Area")} </span>
              <span className="font-medium">{formatArea(m.area_m2)}</span>
            </span>
          )}
          {m.length_m != null && (
            <span>
              <span className="text-muted-foreground">
                {circle
                  ? t("Circumference")
                  : m.area_m2 != null
                    ? t("Perimeter")
                    : t("Length")}{" "}
              </span>
              <span className="font-medium">{formatLength(m.length_m)}</span>
            </span>
          )}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {purpose === "draw" && (
          <Button
            size="sm"
            className="h-8"
            disabled={geometry === null}
            onClick={onSave}
          >
            {t("Save as feature")}
          </Button>
        )}
        <Button
          variant={purpose === "draw" ? "outline" : "default"}
          size="sm"
          className="h-8"
          onClick={onCancel}
        >
          {purpose === "draw" ? t("Cancel") : t("Done")}
        </Button>
      </div>
    </div>
  );
}

const schema = z.object({
  name: z.string().min(1).max(200),
  feature_type: z.enum(["site", "zone", "geofence", "route"]),
});
export type SaveFeatureValues = z.infer<typeof schema>;

/** Name and type for a drawing that becomes a feature. */
export function SaveFeatureDialog({
  open,
  geometry,
  pending,
  error,
  onOpenChange,
  onSave,
}: {
  open: boolean;
  geometry: GeoJSON.Geometry | null;
  pending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onSave: (values: SaveFeatureValues) => void;
}) {
  const { t } = useTranslation();
  const types = featureTypesFor(geometry);
  const form = useForm<SaveFeatureValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", feature_type: types[0] },
    values: { name: "", feature_type: types[0] },
    resetOptions: { keepDirtyValues: true },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("Save as feature")}</DialogTitle>
          <DialogDescription>
            {t(
              "The drawing becomes a feature of the project, shown on the map and usable in rules.",
            )}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((v) => onSave(v))}
          noValidate
        >
          <Field
            label={t("Name")}
            htmlFor="draw-feature-name"
            error={form.formState.errors.name?.message}
          >
            <Input
              id="draw-feature-name"
              autoFocus
              {...form.register("name")}
            />
          </Field>
          <Field label={t("Type")} htmlFor="draw-feature-type">
            <Select
              value={form.watch("feature_type")}
              onValueChange={(v) =>
                form.setValue(
                  "feature_type",
                  v as SaveFeatureValues["feature_type"],
                )
              }
            >
              <SelectTrigger id="draw-feature-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {types.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {error && <Callout kind="error">{error}</Callout>}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {t("Cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {t("Save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
