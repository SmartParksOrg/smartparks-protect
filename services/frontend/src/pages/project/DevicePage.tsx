import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, MapPin } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  DeviceDataSpan,
  DeviceDetail,
  DeviceType,
  Page as PageType,
  Position,
  TrafficRow,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { TechnicalDetails } from "@/components/common/TechnicalDetails";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DeviceControl } from "@/components/control/DeviceControl";
import {
  CuratedBadge,
  CurateDialog,
  RecordHistoryDialog,
} from "@/components/curation/CurationDialogs";
import { HealthCard } from "@/components/devices/HealthCard";
import { LogFilesCard } from "@/components/devices/LogFilesCard";
import { TrafficTable } from "@/components/network/TrafficTable";
import {
  RecordDeliveriesDialog,
  SourceEventDialog,
} from "@/components/devices/ProvenancePanel";
import { WebBleCard } from "@/components/devices/WebBleCard";
import { Icon } from "@/components/icons/Icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useNow } from "@/hooks/useNow";
import { useTechnicalDetails } from "@/hooks/useTechnicalDetails";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { type CurationTarget } from "@/lib/curation";
import { formatAgo, formatTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

export function DevicePage() {
  const { t } = useTranslation();
  const { projectId, deviceId = "" } = useParams();
  const user = useAuthStore((s) => s.user);
  const role = useProjectRole(projectId);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(
    null,
  );
  const [record, setRecord] = useState<number | null>(null);
  const [curating, setCurating] = useState<CurationTarget | null>(null);
  const [history, setHistory] = useState<CurationTarget | null>(null);
  const device = useQuery({
    queryKey: queryKeys.device(deviceId),
    queryFn: () => api.get<DeviceDetail>(`/api/v1/devices/${deviceId}`),
  });
  const types = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", {
        query: { limit: 500 },
      }),
  });
  const positions = useQuery({
    queryKey: queryKeys.positions(projectId ?? "", { deviceId, recent: true }),
    queryFn: () =>
      api.get<Position[]>(`/api/v1/projects/${projectId}/positions`, {
        query: {
          device_id: deviceId,
          limit: 10,
          from: new Date(Date.now() - 30 * 86400_000).toISOString(),
        },
      }),
    enabled: Boolean(projectId),
  });
  const span = useQuery({
    queryKey: queryKeys.deviceSpan(deviceId),
    queryFn: () =>
      api.get<DeviceDataSpan>(`/api/v1/devices/${deviceId}/data-span`),
  });
  const traffic = useQuery({
    queryKey: queryKeys.traffic(projectId ?? "", { deviceId, recent: true }),
    queryFn: () =>
      api.get<TrafficRow[]>(`/api/v1/projects/${projectId}/traffic`, {
        query: {
          device_id: deviceId,
          limit: 20,
          from: new Date(Date.now() - 7 * 86400_000).toISOString(),
        },
      }),
    enabled: Boolean(projectId),
    refetchInterval: 15_000,
  });
  const now = useNow();
  const [technical] = useTechnicalDetails();
  const repairInvalidate = [
    queryKeys.device(deviceId),
    queryKeys.deviceSpan(deviceId),
    queryKeys.positions(projectId ?? "", { deviceId, recent: true }),
  ];
  const extendProject = useMutationToast({
    mutationFn: (s: DeviceDataSpan) =>
      api.post(
        `/api/v1/devices/${deviceId}/project-assignments/${s.earliest_project_assignment_id}/extend-start`,
        { body: { valid_from: s.first_data_at } },
      ),
    invalidate: repairInvalidate,
    success: t(
      "Assignment extended; the earlier records now belong to the project",
    ),
  });
  const extendEntity = useMutationToast({
    mutationFn: (s: DeviceDataSpan) =>
      api.post(
        `/api/v1/projects/${projectId}/entity-assignments/${s.earliest_entity_assignment_id}/extend-start`,
        { body: { valid_from: s.first_data_at } },
      ),
    invalidate: repairInvalidate,
    success: t(
      "Assignment extended; the earlier records now belong to the entity",
    ),
  });
  const d = device.data;
  const type = types.data?.items.find((t) => t.id === d?.device_type_id);
  const sp = span.data;
  const beforeProject = sp
    ? sp.before_project.positions + sp.before_project.measurements
    : 0;
  const beforeEntity = sp
    ? sp.before_entity.positions + sp.before_entity.measurements
    : 0;
  const mayRepair = Boolean(user?.is_superuser || canAdmin(role));
  const firstData = sp?.first_data_at ?? null;
  const projectCovered = Boolean(
    sp?.earliest_project_from &&
    firstData &&
    new Date(sp.earliest_project_from) <= new Date(firstData),
  );
  const currentEntityId =
    d?.entity_assignments.find((a) => !a.valid_to)?.entity_id ?? null;
  if (device.isError)
    return (
      <Page>
        <div className="text-destructive">{device.error.message}</div>
      </Page>
    );
  if (!d)
    return (
      <Page>
        <div className="text-muted-foreground">{t("Loading device…")}</div>
      </Page>
    );

  return (
    <>
      <PageHeader
        title={d.name}
        description={type ? `${type.label} (${type.driver_key})` : undefined}
        actions={
          <>
            <StatusBadge value={d.status} />
            {(d.links ?? []).map((link) => (
              <Button key={link.key} asChild variant="outline" size="sm">
                <a href={link.url} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-4" /> {link.label}
                </a>
              </Button>
            ))}
            {projectId && currentEntityId && (
              <Button asChild variant="outline" size="sm">
                <Link
                  to={`/projects/${projectId}/map?entity=${currentEntityId}`}
                >
                  <MapPin className="size-4" /> {t("Show on map")}
                </Link>
              </Button>
            )}
            {user?.is_superuser && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/admin/devices?device=${d.id}`}>{t("Manage")}</Link>
              </Button>
            )}
          </>
        }
      />
      <Page>
        {sp && beforeProject > 0 && sp.earliest_project_assignment_id && (
          <Callout kind="warning">
            {t(
              "{{count}} records from before {{date}} belong to no project and stay invisible here.",
              {
                count: beforeProject,
                date: formatTime(sp.earliest_project_from),
              },
            )}{" "}
            {mayRepair && firstData && (
              <Button
                size="sm"
                variant="outline"
                className="mt-2 h-auto max-w-full whitespace-normal text-left sm:ml-2 sm:mt-0"
                disabled={extendProject.isPending}
                onClick={() => extendProject.mutate(sp)}
              >
                {t("Extend the assignment back to {{date}}", {
                  date: formatTime(firstData),
                })}
              </Button>
            )}
          </Callout>
        )}
        {sp &&
          beforeProject === 0 &&
          beforeEntity > 0 &&
          sp.earliest_entity_assignment_id &&
          projectId && (
            <Callout kind="info">
              {t(
                "{{count}} records from before {{date}} belong to no entity.",
                {
                  count: beforeEntity,
                  date: formatTime(sp.earliest_entity_from),
                },
              )}{" "}
              {mayRepair && firstData && projectCovered && (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2 h-auto max-w-full whitespace-normal text-left sm:ml-2 sm:mt-0"
                  disabled={extendEntity.isPending}
                  onClick={() => extendEntity.mutate(sp)}
                >
                  {t("Extend the entity assignment back to {{date}}", {
                    date: formatTime(firstData),
                  })}
                </Button>
              )}
            </Callout>
          )}
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Icon iconKey={type?.icon_key} /> {t("Device")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">{t("Serial")}</dt>
                <dd>{d.serial_number ?? "none"}</dd>
                <dt className="text-muted-foreground">{t("Firmware")}</dt>
                <dd>{d.firmware_version ?? "unknown"}</dd>
                <dt className="text-muted-foreground">{t("Created")}</dt>
                <dd>{formatTime(d.created_at)}</dd>
                <dt className="text-muted-foreground">{t("Notes")}</dt>
                <dd>{d.notes ?? ""}</dd>
              </dl>
            </CardContent>
          </Card>
          <HealthCard health={d.health} />
          <Card>
            <CardHeader>
              <CardTitle>{t("Project assignments")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {d.project_assignments.length === 0 && (
                <div className="text-muted-foreground">
                  {t("Not assigned to a project.")}
                </div>
              )}
              {d.project_assignments.map((a) => (
                <div key={a.id}>
                  {t("{{from}} to {{to}}", {
                    from: formatTime(a.valid_from),
                    to: a.valid_to ? formatTime(a.valid_to) : t("now"),
                  })}
                  {a.reason ? `, ${a.reason}` : ""}
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("Entity assignments")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {d.entity_assignments.length === 0 && (
                <div className="text-muted-foreground">
                  {t("Not assigned to an entity.")}
                </div>
              )}
              {d.entity_assignments.map((a) => (
                <div key={a.id}>
                  {projectId ? (
                    <Link
                      className="underline"
                      to={`/projects/${projectId}/entities/${a.entity_id}`}
                    >
                      {a.entity_name ?? a.entity_id.slice(0, 8)}
                    </Link>
                  ) : (
                    <span>{a.entity_name ?? a.entity_id.slice(0, 8)}</span>
                  )}
                  ,{" "}
                  {t("{{from}} to {{to}}", {
                    from: formatTime(a.valid_from),
                    to: a.valid_to ? formatTime(a.valid_to) : t("now"),
                  })}
                </div>
              ))}
            </CardContent>
          </Card>
          <div className="lg:col-span-2">
            <DeviceControl
              deviceId={d.id}
              projectId={projectId}
              canFlush={canAdmin(role) || Boolean(user?.is_superuser)}
            />
          </div>
          <WebBleCard
            deviceId={d.id}
            deviceName={d.name}
            driverKey={type?.driver_key}
            canWrite={canAdmin(role) || Boolean(user?.is_superuser)}
          />
          <LogFilesCard
            deviceId={d.id}
            canWrite={canAdmin(role) || Boolean(user?.is_superuser)}
          />
          <TechnicalDetails className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>{t("External identities")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {d.external_identities.length === 0 && (
                  <div className="text-muted-foreground">
                    {t(
                      "No identity yet. Data for this device cannot be received until a DevEUI or provider id is linked.",
                    )}
                  </div>
                )}
                {d.external_identities.map((i) => (
                  <div key={i.id} className="flex flex-wrap items-center gap-2">
                    <span className="font-mono">{i.external_id}</span>
                    <Badge variant="outline">{i.identity_type}</Badge>
                    <span className="text-muted-foreground">
                      {i.event_count} {t("events, last")}{" "}
                      {formatAgo(i.last_seen_at, now)}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
            {projectId && (
              <Card className="lg:col-span-2">
                <CardHeader className="flex flex-row items-center justify-between">
                  <CardTitle>{t("Traffic")}</CardTitle>
                  <Button
                    asChild
                    variant="link"
                    size="sm"
                    className="h-auto p-0"
                  >
                    <Link
                      to={`/projects/${projectId}/network/traffic?device=${d.id}`}
                    >
                      {t("All traffic of this device")}
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
          </TechnicalDetails>
          {projectId && (
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("Recent positions")}</CardTitle>
              </CardHeader>
              <CardContent>
                {positions.data?.length === 0 && (
                  <div className="text-sm text-muted-foreground">
                    {t("No positions in the last 30 days.")}
                  </div>
                )}
                <ul className="divide-y text-sm">
                  {positions.data?.map((p) => (
                    <li
                      key={p.id}
                      className="flex flex-wrap items-center gap-3 py-1.5"
                    >
                      <span>{formatTime(p.time)}</span>
                      <span className="font-mono text-xs">
                        {(p.geometry?.coordinates as number[])?.[1]?.toFixed(5)}
                        ,{" "}
                        {(p.geometry?.coordinates as number[])?.[0]?.toFixed(5)}
                      </span>
                      {p.accuracy_m != null && (
                        <span className="text-muted-foreground">
                          {t("±{{value}} m", { value: p.accuracy_m })}
                        </span>
                      )}
                      <CuratedBadge
                        curatedFields={p.curated_fields ?? []}
                        valid={p.valid ?? true}
                        onClick={() =>
                          setHistory({
                            target_type: "position",
                            target_id: p.id,
                            target_time: p.original_time,
                          })
                        }
                      />
                      <span className="ml-auto flex gap-3">
                        {projectId &&
                          (canAdmin(role) || user?.is_superuser) && (
                            <Button
                              variant="link"
                              size="sm"
                              className="h-auto p-0"
                              onClick={() =>
                                setCurating({
                                  target_type: "position",
                                  target_id: p.id,
                                  target_time: p.original_time,
                                })
                              }
                            >
                              {t("curate")}
                            </Button>
                          )}
                        {technical && (
                          <Button
                            variant="link"
                            size="sm"
                            className="h-auto p-0"
                            onClick={() => setRecord(p.id)}
                          >
                            {t("deliveries")}
                          </Button>
                        )}
                        {technical && p.source_event_id != null && (
                          <Button
                            variant="link"
                            size="sm"
                            className="h-auto p-0"
                            onClick={() =>
                              setEvent({
                                id: p.source_event_id!,
                                ingestedAt: p.ingested_at,
                              })
                            }
                          >
                            {t("provenance")}
                          </Button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </Page>
      <SourceEventDialog
        id={event?.id ?? null}
        ingestedAt={event?.ingestedAt ?? null}
        onClose={() => setEvent(null)}
      />
      <RecordDeliveriesDialog
        canonicalType="position"
        canonicalId={record}
        onClose={() => setRecord(null)}
        onOpenEvent={(id, ingestedAt) => {
          setRecord(null);
          setEvent({ id, ingestedAt });
        }}
      />
      {projectId && (
        <CurateDialog
          projectId={projectId}
          target={curating}
          onClose={() => {
            setCurating(null);
            void positions.refetch();
          }}
        />
      )}
      {projectId && (
        <RecordHistoryDialog
          projectId={projectId}
          target={history}
          onClose={() => setHistory(null)}
        />
      )}
    </>
  );
}
