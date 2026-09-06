import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { MapPin, Pencil, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  CurrentState,
  Device,
  Entity,
  EntityAssignment,
  EntityType,
  Page as PageType,
} from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { HealthCard } from "@/components/devices/HealthCard";
import { AssignDeviceDialog } from "@/components/entities/AssignDeviceDialog";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { Icon } from "@/components/icons/Icon";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { groupPath, useGroups } from "@/hooks/useGroups";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";

/** One entity: what it is, the device tracking it now with its health, and the history of the
 * devices that tracked it, with "Assign device" for project admins (decision D106). */
export function EntityPage() {
  const { t } = useTranslation();
  const { projectId = "", entityId = "" } = useParams();
  const role = useProjectRole(projectId);
  const now = useNow();
  const [editing, setEditing] = useState(false);
  const [assigning, setAssigning] = useState(false);
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
  const assignments = useQuery({
    queryKey: queryKeys.entityAssignments(projectId, { entityId }),
    queryFn: () =>
      api.get<PageType<EntityAssignment>>(
        `/api/v1/projects/${projectId}/entity-assignments`,
        { query: { entity_id: entityId, limit: 500 } },
      ),
  });
  const state = useQuery({
    queryKey: queryKeys.currentState(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`),
  });
  const history = useMemo(
    () =>
      [...(assignments.data?.items ?? [])].sort((a, b) =>
        b.valid_from.localeCompare(a.valid_from),
      ),
    [assignments.data],
  );
  const current = history.find((a) => !a.valid_to) ?? null;
  const device = useQuery({
    queryKey: queryKeys.device(current?.device_id ?? ""),
    queryFn: () => api.get<Device>(`/api/v1/devices/${current?.device_id}`),
    enabled: Boolean(current),
  });
  const live = useMemo(
    () =>
      (
        state.data?.features as unknown as
          { properties: EntityFeatureProperties }[] | undefined
      )?.find((f) => f.properties.entity_id === entityId)?.properties ?? null,
    [state.data, entityId],
  );
  const release = useMutationToast({
    mutationFn: (assignmentId: string) =>
      api.patch(
        `/api/v1/projects/${projectId}/entity-assignments/${assignmentId}`,
        { body: { valid_to: new Date().toISOString() } },
      ),
    invalidate: [
      queryKeys.entityAssignments(projectId),
      queryKeys.devices({ projectId, unassigned: true }),
      queryKeys.currentState(projectId),
      ...(current ? [queryKeys.device(current.device_id)] : []),
    ],
    success: t("Device released; it tracks nothing from now"),
  });
  const e = entity.data;
  const type = types.data?.items.find((x) => x.id === e?.entity_type_id);
  const groups = useGroups(projectId);
  const path = groupPath(groups.data, e?.group_id);
  const admin = canAdmin(role);
  const point =
    e?.geometry?.type === "Point" ? (e.geometry.coordinates as number[]) : null;
  if (entity.isError)
    return (
      <Page>
        <div className="text-destructive">{entity.error.message}</div>
      </Page>
    );
  if (!e)
    return (
      <Page>
        <div className="text-muted-foreground">{t("Loading entity…")}</div>
      </Page>
    );

  return (
    <>
      <PageHeader
        title={e.name}
        description={type?.label}
        actions={
          <>
            <Icon
              iconKey={e.icon_key ?? type?.icon_key}
              className="size-6 text-primary"
            />
            <StatusBadge value={e.status} />
            {live?.position_time && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/projects/${projectId}/map?entity=${e.id}`}>
                  <MapPin className="size-4" /> {t("Show on map")}
                </Link>
              </Button>
            )}
            {admin && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditing(true)}
              >
                <Pencil className="size-4" /> {t("Edit")}
              </Button>
            )}
          </>
        }
      />
      <Page>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>{t("Entity")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">{t("Type")}</dt>
                <dd>{type?.label ?? ""}</dd>
                {e.group_id && (
                  <>
                    <dt className="text-muted-foreground">{t("Group")}</dt>
                    <dd>{path}</dd>
                  </>
                )}
                <dt className="text-muted-foreground">{t("Last seen")}</dt>
                <dd title={formatTime(live?.last_seen_at)}>
                  {live?.last_seen_at
                    ? formatAgo(live.last_seen_at, now)
                    : t("never")}
                </dd>
                <dt className="text-muted-foreground">{t("Last position")}</dt>
                <dd>
                  {live?.position_time
                    ? formatTime(live.position_time)
                    : t("none")}
                </dd>
                {point && (
                  <>
                    <dt className="text-muted-foreground">
                      {t("Static location")}
                    </dt>
                    <dd className="font-mono text-xs">
                      {point[1]?.toFixed(5)}, {point[0]?.toFixed(5)}
                    </dd>
                  </>
                )}
                {live && live.active_alert_count > 0 && (
                  <>
                    <dt className="text-muted-foreground">{t("Alerts")}</dt>
                    <dd>
                      <Link
                        className="underline"
                        to={`/projects/${projectId}/alerts`}
                      >
                        {live.active_alert_count} {t("open")}
                      </Link>
                    </dd>
                  </>
                )}
                <dt className="text-muted-foreground">{t("Created")}</dt>
                <dd>{formatTime(e.created_at)}</dd>
                {e.notes && (
                  <>
                    <dt className="text-muted-foreground">{t("Notes")}</dt>
                    <dd>{e.notes}</dd>
                  </>
                )}
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t("Device")}</CardTitle>
              {admin && !current && (
                <Button size="sm" onClick={() => setAssigning(true)}>
                  <Plus className="size-4" /> {t("Assign device")}
                </Button>
              )}
            </CardHeader>
            <CardContent className="text-sm">
              {!current && (
                <div className="text-muted-foreground">
                  {t("No device tracks this entity today.")}
                </div>
              )}
              {current && (
                <div className="flex flex-wrap items-center gap-3">
                  <Link
                    className="font-medium underline"
                    to={`/projects/${projectId}/devices/${current.device_id}`}
                  >
                    {current.device_name ?? t("open device")}
                  </Link>
                  {device.data?.serial_number && (
                    <span className="font-mono text-xs text-muted-foreground">
                      {device.data.serial_number}
                    </span>
                  )}
                  <span className="text-muted-foreground">
                    {t("since {{date}}", {
                      date: formatTime(current.valid_from),
                    })}
                  </span>
                  <span className="text-muted-foreground">
                    {t("last seen")} {formatAgo(device.data?.last_seen_at, now)}
                  </span>
                  {admin && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      disabled={release.isPending}
                      onClick={() => release.mutate(current.id)}
                    >
                      {t("Release device")}
                    </Button>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
          {current && <HealthCard health={device.data?.health} />}
          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t("Assignments")}</CardTitle>
              {admin && current && (
                <span className="text-xs text-muted-foreground">
                  {t("Release the current device to assign another.")}
                </span>
              )}
            </CardHeader>
            <CardContent>
              {assignments.isPending && (
                <div className="text-sm text-muted-foreground">
                  {t("Loading…")}
                </div>
              )}
              {assignments.data && history.length === 0 && (
                <div className="text-sm text-muted-foreground">
                  {t("No device has tracked this entity yet.")}
                </div>
              )}
              {history.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("Device")}</TableHead>
                      <TableHead>{t("From")}</TableHead>
                      <TableHead>{t("To")}</TableHead>
                      <TableHead>{t("Reason")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {history.map((a) => (
                      <TableRow key={a.id}>
                        <TableCell>
                          <Link
                            className="underline"
                            to={`/projects/${projectId}/devices/${a.device_id}`}
                          >
                            {a.device_name ?? a.device_id.slice(0, 8)}
                          </Link>
                        </TableCell>
                        <TableCell>{formatTime(a.valid_from)}</TableCell>
                        <TableCell>
                          {a.valid_to ? formatTime(a.valid_to) : t("now")}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {a.reason ?? ""}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </Page>
      <EntityDialog
        projectId={projectId}
        entity={e}
        open={editing}
        onOpenChange={setEditing}
      />
      <AssignDeviceDialog
        projectId={projectId}
        entityId={e.id}
        entityName={e.name}
        open={assigning}
        onOpenChange={setAssigning}
      />
    </>
  );
}
