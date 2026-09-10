import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { MapPin, Pencil, Plus, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  CurrentState,
  Device,
  DeviceDataSpan,
  Entity,
  EntityAssignment,
  EntityType,
  EventItem,
  Page as PageType,
  Position,
  TrafficRow,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { TrafficTable } from "@/components/network/TrafficTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { HealthCard } from "@/components/devices/HealthCard";
import { AssignDeviceDialog } from "@/components/entities/AssignDeviceDialog";
import { ChangeAssignmentDialog } from "@/components/entities/ChangeAssignmentDialog";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { Icon } from "@/components/icons/Icon";
import { PictureEditor } from "@/components/common/PictureEditor";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { recordsHref } from "@/lib/records";
import { MiniMap } from "@/components/map/MiniMap";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConnectivityCards } from "@/components/devices/ConnectivityCard";
import { LocationSourceCard } from "@/components/devices/LocationSourceCard";
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
import { useAt } from "@/hooks/useAt";
import { useTab } from "@/hooks/useTab";
import { groupPath, useGroups } from "@/hooks/useGroups";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";

/** One entity: what it is, the device tracking it now with its health, and the history of the
 * devices that tracked it, with "Assign device" for project admins (decision D106). */
const TABS = ["overview", "data", "connectivity", "network"] as const;

export function EntityPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useTab(TABS);
  const [connectivityHours, setConnectivityHours] = useState(168);
  const { projectId = "", entityId = "" } = useParams();
  const role = useProjectRole(projectId);
  const now = useNow();
  const [editing, setEditing] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [changing, setChanging] = useState<EntityAssignment | null>(null);
  const [since30d] = useState(() =>
    new Date(Date.now() - 30 * 86400_000).toISOString(),
  );
  const [since7d] = useState(() =>
    new Date(Date.now() - 7 * 86400_000).toISOString(),
  );
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(
    null,
  );
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
  const events = useQuery({
    queryKey: queryKeys.events(projectId, { entity_id: entityId, limit: 10 }),
    queryFn: () =>
      api.get<PageType<EventItem>>(`/api/v1/projects/${projectId}/events`, {
        query: { entity_id: entityId, limit: 10 },
      }),
    refetchInterval: 60_000,
  });
  const around = useAt();
  const positions = useQuery({
    queryKey: queryKeys.positions(projectId, {
      entityId,
      recent: true,
      at: around.at,
    }),
    queryFn: () =>
      api.get<Position[]>(`/api/v1/projects/${projectId}/positions`, {
        query: around.at
          ? { entity_id: entityId, limit: 50, from: around.from, to: around.to }
          : { entity_id: entityId, limit: 10, from: since30d },
      }),
  });
  const traffic = useQuery({
    queryKey: queryKeys.traffic(projectId, {
      deviceId: current?.device_id ?? "",
      recent: true,
    }),
    queryFn: () =>
      api.get<TrafficRow[]>(`/api/v1/projects/${projectId}/traffic`, {
        query: {
          device_id: current?.device_id,
          limit: 20,
          from:
            current && current.valid_from > since7d
              ? current.valid_from
              : since7d,
          to: current?.valid_to ?? undefined,
        },
      }),
    enabled: Boolean(current),
    refetchInterval: 15_000,
  });
  const span = useQuery({
    queryKey: queryKeys.deviceSpan(current?.device_id ?? ""),
    queryFn: () =>
      api.get<DeviceDataSpan>(
        `/api/v1/devices/${current?.device_id}/data-span`,
      ),
    enabled: Boolean(current),
  });
  const extend = useMutationToast({
    mutationFn: (s: DeviceDataSpan) =>
      api.post(
        `/api/v1/projects/${projectId}/entity-assignments/${current?.id}/extend-start`,
        { body: { valid_from: s.first_data_at } },
      ),
    invalidate: [
      queryKeys.entityAssignments(projectId),
      queryKeys.currentState(projectId),
      queryKeys.positions(projectId, { entityId, recent: true }),
      ...(current
        ? [
            queryKeys.deviceSpan(current.device_id),
            queryKeys.device(current.device_id),
          ]
        : []),
    ],
    success: t(
      "Assignment extended; the earlier records now belong to this entity",
    ),
  });
  const sp = span.data;
  const beforeEntity =
    sp && current && sp.earliest_entity_assignment_id === current.id
      ? sp.before_entity.positions + sp.before_entity.measurements
      : 0;
  const projectCovered = Boolean(
    sp?.earliest_project_from &&
    sp?.first_data_at &&
    new Date(sp.earliest_project_from) <= new Date(sp.first_data_at),
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
        leading={
          <PictureEditor
            path={`/api/v1/projects/${projectId}/entities/${e.id}/picture`}
            updatedAt={e.picture_updated_at}
            name={e.name}
            editable={admin}
            invalidate={[
              queryKeys.entity(projectId, e.id),
              queryKeys.entities(projectId),
              queryKeys.currentState(projectId),
            ]}
            fallback={
              <Icon iconKey={e.icon_key ?? type?.icon_key} className="size-6" />
            }
          />
        }
        actions={
          <>
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
        {current && sp && beforeEntity > 0 && (
          <Callout kind="info">
            {t(
              "{{count}} records of {{device}} from before {{date}} belong to no entity, so they are not on this page or the map.",
              {
                count: beforeEntity,
                device: current.device_name ?? t("the device"),
                date: formatTime(current.valid_from),
              },
            )}{" "}
            {admin && sp.first_data_at && projectCovered && (
              <Button
                size="sm"
                variant="outline"
                className="mt-2 h-auto max-w-full whitespace-normal text-left sm:ml-2 sm:mt-0"
                disabled={extend.isPending}
                onClick={() => extend.mutate(sp)}
              >
                {t("Extend the assignment back to {{date}}", {
                  date: formatTime(sp.first_data_at),
                })}
              </Button>
            )}
            {admin && sp.first_data_at && !projectCovered && (
              <span className="ml-2 text-xs">
                {t(
                  "The device joined the project later than its first data; extend the project assignment on the device page first.",
                )}
              </span>
            )}
          </Callout>
        )}
        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as (typeof TABS)[number])}
        >
          <TabsList>
            <TabsTrigger value="overview">{t("Overview")}</TabsTrigger>
            <TabsTrigger value="data">{t("Data")}</TabsTrigger>
            <TabsTrigger value="connectivity">{t("Connectivity")}</TabsTrigger>
            <TabsTrigger value="network">{t("Network")}</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
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
                    <dt className="text-muted-foreground">
                      {t("Last position")}
                    </dt>
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
              <MiniMap
                positions={positions.data ?? []}
                to={`/projects/${projectId}/map?entity=${e.id}`}
              />
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
                        {t("last seen")}{" "}
                        {formatAgo(device.data?.last_seen_at, now)}
                      </span>
                      {admin && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="ml-auto"
                          onClick={() => setChanging(current)}
                        >
                          {t("Change…")}
                        </Button>
                      )}
                      {admin && (
                        <Button
                          variant="outline"
                          size="sm"
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
              <LocationSourceCard
                key={`${e.location_source ?? "device"}-${e.location_fallback_hours ?? 24}`}
                path={`/api/v1/projects/${projectId}/entities/${e.id}`}
                value={e.location_source ?? "device"}
                fallbackHours={e.location_fallback_hours ?? 24}
                invalidate={[queryKeys.entity(projectId, e.id)]}
                canEdit={admin}
              />
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
                          <TableHead className="w-24" />
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
                            <TableCell className="text-right">
                              {admin && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 px-2 text-xs"
                                  onClick={() => setChanging(a)}
                                >
                                  {t("Change…")}
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>
          <TabsContent value="data">
            <div className="mb-3 flex justify-end">
              <Button asChild variant="outline" size="sm">
                <Link
                  to={recordsHref(projectId, {
                    entities: [e.id],
                    at: around.at,
                  })}
                >
                  <Table2 className="size-4" /> {t("All records")}
                </Link>
              </Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>{t("Recent events")}</CardTitle>
                  <Button
                    asChild
                    variant="link"
                    size="sm"
                    className="h-auto p-0"
                  >
                    <Link to={`/projects/${projectId}/rules/events`}>
                      {t("All events")}
                    </Link>
                  </Button>
                </CardHeader>
                <CardContent>
                  {events.data && events.data.items.length === 0 && (
                    <div className="text-sm text-muted-foreground">
                      {t("No events for this entity yet.")}
                    </div>
                  )}
                  <ul className="divide-y text-sm">
                    {events.data?.items.map((ev) => (
                      <li
                        key={ev.id}
                        className="flex flex-wrap items-center gap-2 py-1.5"
                      >
                        <StatusBadge value={ev.severity} />
                        <Link
                          className="font-medium hover:underline"
                          to={`/projects/${projectId}/rules/events?event=${ev.id}`}
                        >
                          {ev.title}
                        </Link>
                        <span
                          className="ml-auto text-xs text-muted-foreground"
                          title={formatTime(ev.time)}
                        >
                          {formatAgo(ev.time, now)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>{t("Recent positions")}</CardTitle>
                  {live?.position_time && (
                    <Button
                      asChild
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                    >
                      <Link
                        to={`/projects/${projectId}/map?entity=${e.id}&tracks=${e.id}&track=24`}
                      >
                        {t("Track on the map")}
                      </Link>
                    </Button>
                  )}
                </CardHeader>
                <CardContent>
                  {around.at && (
                    <div className="mb-2 text-sm text-muted-foreground">
                      {t("Around {{time}}.", { time: formatTime(around.at) })}{" "}
                      <button
                        type="button"
                        className="underline"
                        onClick={around.clear}
                      >
                        {t("Show the latest instead")}
                      </button>
                    </div>
                  )}
                  {positions.data?.length === 0 && (
                    <div className="text-sm text-muted-foreground">
                      {around.at
                        ? t("No positions within 12 hours of that time.")
                        : t("No positions in the last 30 days.")}
                    </div>
                  )}
                  <ul className="divide-y text-sm">
                    {positions.data?.map((p) => (
                      <li
                        key={p.id}
                        className={`flex flex-wrap items-center gap-3 py-1.5 ${around.isAt(p.time) ? "rounded bg-muted px-1 font-medium" : ""}`}
                      >
                        <span>{formatTime(p.time)}</span>
                        <span className="font-mono text-xs">
                          {(p.geometry?.coordinates as number[])?.[1]?.toFixed(
                            5,
                          )}
                          ,{" "}
                          {(p.geometry?.coordinates as number[])?.[0]?.toFixed(
                            5,
                          )}
                        </span>
                        {p.accuracy_m != null && (
                          <span className="text-muted-foreground">
                            {t("±{{value}} m", { value: p.accuracy_m })}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
          <TabsContent value="connectivity">
            {current ? (
              <ConnectivityCards
                deviceId={current.device_id}
                projectId={projectId}
                hours={connectivityHours}
                onHoursChange={setConnectivityHours}
              />
            ) : (
              <Callout kind="info">
                {t(
                  "No device tracks this entity today, so there is no network to report on.",
                )}
              </Callout>
            )}
          </TabsContent>
          <TabsContent value="network">
            <div className="grid gap-4 [&>*]:min-w-0">
              {!current && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "No device tracks this entity today, so there is no traffic to show.",
                  )}
                </p>
              )}
              {current && (
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between">
                    <CardTitle>
                      {t("Traffic of {{device}}", {
                        device: current.device_name ?? t("the device"),
                      })}
                    </CardTitle>
                    <Button
                      asChild
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                    >
                      <Link
                        to={`/projects/${projectId}/devices/${current.device_id}?tab=network`}
                      >
                        {t("The device's network tab")}
                      </Link>
                    </Button>
                  </CardHeader>
                  <CardContent>
                    <TrafficTable
                      rows={traffic.data}
                      isLoading={traffic.isPending}
                      emptyMessage={t("No messages in the last 7 days.")}
                      onSelect={(r) =>
                        setEvent({
                          id: r.source_event_id,
                          ingestedAt: r.ingested_at,
                        })
                      }
                    />
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
        </Tabs>
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
      <SourceEventDialog
        id={event?.id ?? null}
        ingestedAt={event?.ingestedAt ?? null}
        onClose={() => setEvent(null)}
      />
      {changing && (
        <ChangeAssignmentDialog
          projectId={projectId}
          assignment={changing}
          open
          onOpenChange={(o) => !o && setChanging(null)}
        />
      )}
    </>
  );
}
