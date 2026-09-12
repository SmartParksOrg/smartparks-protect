import { useTranslation } from "react-i18next";
import { Layers } from "lucide-react";
import { Link } from "react-router";

import type { Feature } from "@/api/types";
import { ruleTemplateFor } from "@/components/map/featureTools";
import { MapPanel, PanelRow } from "@/components/map/MapObjectPanel";
import { Button } from "@/components/ui/button";
import { formatArea, formatLength, measure } from "@/lib/geodesy";

/**
 * A feature on the live map (phase 19): its type, what it measures, and the way to a rule on
 * it, the Features page and the rules.
 */
export function FeaturePanel({
  feature,
  projectId,
  canWriteRules,
  wasHidden,
  onClose,
}: {
  feature: Feature;
  projectId: string;
  canWriteRules: boolean;
  wasHidden: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const geometry = (feature.geometry ?? null) as GeoJSON.Geometry | null;
  const m = measure(geometry);
  const template = ruleTemplateFor(feature.feature_type);
  const point =
    geometry?.type === "Point"
      ? (geometry.coordinates as [number, number])
      : null;
  // a circle is a polygon that remembers its radius (decision D172)
  const attributes = (feature.attributes ?? {}) as Record<string, unknown>;
  const radius =
    attributes.shape === "circle" && typeof attributes.radius_m === "number"
      ? attributes.radius_m
      : null;
  return (
    <MapPanel
      title={feature.name}
      titleTo={`/projects/${projectId}/admin/features`}
      subtitle={
        radius != null
          ? t("{{type}}, circle of {{radius}}", {
              type: feature.feature_type,
              radius: formatLength(radius),
            })
          : feature.feature_type
      }
      picture={
        <span className="flex size-9 items-center justify-center rounded-md bg-muted">
          <Layers className="size-5 text-primary" />
        </span>
      }
      note={
        wasHidden
          ? t("Hidden in the layers panel until now; it stays shown.")
          : undefined
      }
      onClose={onClose}
      footer={
        template && canWriteRules ? (
          <Button asChild size="sm" className="h-8">
            <Link
              to={`/projects/${projectId}/rules?new=${template}&feature=${feature.id}`}
            >
              {t("Create rule")}
            </Link>
          </Button>
        ) : undefined
      }
    >
      {point && (
        <PanelRow label={t("Position")}>
          <span className="font-mono text-xs">
            {point[1].toFixed(5)}, {point[0].toFixed(5)}
          </span>
        </PanelRow>
      )}
      {radius != null && (
        <PanelRow label={t("Radius")}>{formatLength(radius)}</PanelRow>
      )}
      {m.area_m2 != null && (
        <PanelRow label={t("Area")}>{formatArea(m.area_m2)}</PanelRow>
      )}
      {m.length_m != null && (
        <PanelRow
          label={
            radius != null
              ? t("Circumference")
              : m.area_m2 != null
                ? t("Perimeter")
                : t("Length")
          }
        >
          {formatLength(m.length_m)}
        </PanelRow>
      )}
      <PanelRow label={t("More")}>
        <Link
          className="underline"
          to={`/projects/${projectId}/admin/features`}
        >
          {t("features")}
        </Link>
        {" · "}
        <Link className="underline" to={`/projects/${projectId}/rules`}>
          {t("rules")}
        </Link>
      </PanelRow>
    </MapPanel>
  );
}
