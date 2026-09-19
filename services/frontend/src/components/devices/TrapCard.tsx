import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  DeviceTrap,
  Entity,
  EntityType,
  Page as PageType,
} from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";

/**
 * How a TrapEdge's switch is wired (phase 32, decision D266): whether an active switch means
 * the trap is closed. Shown only while the device is on a Trap entity, since the question
 * means nothing elsewhere. Default yes; the field decides.
 */
export function TrapCard({
  deviceId,
  projectId,
  entityId,
  canEdit,
}: {
  deviceId: string;
  projectId: string;
  entityId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const entity = useQuery({
    queryKey: queryKeys.entity(projectId, entityId),
    queryFn: () =>
      api.get<Entity>(`/api/v1/projects/${projectId}/entities/${entityId}`),
  });
  const types = useQuery({
    queryKey: queryKeys.entityTypes,
    queryFn: () =>
      api.get<PageType<EntityType>>("/api/v1/entity-types", {
        query: { limit: 500 },
      }),
  });
  const isTrap =
    types.data?.items.find((x) => x.id === entity.data?.entity_type_id)?.key ===
    "trap";
  const wiring = useQuery({
    queryKey: ["devices", deviceId, "trap"],
    queryFn: () => api.get<DeviceTrap>(`/api/v1/devices/${deviceId}/trap`),
    enabled: isTrap,
  });
  const save = useMutationToast({
    mutationFn: (closedWhenActive: boolean | null) =>
      api.put<DeviceTrap>(`/api/v1/devices/${deviceId}/trap`, {
        body: { closed_when_active: closedWhenActive },
      }),
    invalidate: [["devices", deviceId, "trap"]],
    success: t("Trap wiring saved"),
  });
  if (!isTrap) return null;
  const value =
    wiring.data == null
      ? "active"
      : wiring.data.closed_when_active
        ? "active"
        : "inactive";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Trap")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          {t(
            "Which state of the switch means the trap is closed depends on how the magnet and the contact were mounted. A wrong answer here reports every catch as a release.",
          )}
        </p>
        {canEdit ? (
          <Select
            value={value}
            onValueChange={(v) => save.mutate(v === "active")}
            disabled={save.isPending || !wiring.data}
          >
            <SelectTrigger aria-label={t("Trap wiring")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">
                {t("Closed when the switch is active")}
              </SelectItem>
              <SelectItem value="inactive">
                {t("Closed when the switch is inactive")}
              </SelectItem>
            </SelectContent>
          </Select>
        ) : (
          <p>
            {value === "active"
              ? t("Closed when the switch is active")
              : t("Closed when the switch is inactive")}
          </p>
        )}
        {wiring.data && !wiring.data.set_by_hand && (
          <p className="text-xs text-muted-foreground">
            {t("The default; nobody set it.")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
