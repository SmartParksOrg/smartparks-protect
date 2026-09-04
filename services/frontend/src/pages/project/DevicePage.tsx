import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceDetail, DeviceType, Page as PageType, Position } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DeviceControl } from "@/components/control/DeviceControl";
import { LogFilesCard } from "@/components/devices/LogFilesCard";
import { RecordDeliveriesDialog, SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { WebBleCard } from "@/components/devices/WebBleCard";
import { Icon } from "@/components/icons/Icon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

export function DevicePage() {
  const { projectId, deviceId = "" } = useParams();
  const user = useAuthStore((s) => s.user);
  const role = useProjectRole(projectId);
  const [event, setEvent] = useState<{ id: number; ingestedAt: string } | null>(null);
  const [record, setRecord] = useState<number | null>(null);
  const device = useQuery({ queryKey: queryKeys.device(deviceId), queryFn: () => api.get<DeviceDetail>(`/api/v1/devices/${deviceId}`) });
  const types = useQuery({ queryKey: queryKeys.deviceTypes, queryFn: () => api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }) });
  const positions = useQuery({
    queryKey: queryKeys.positions(projectId ?? "", { deviceId, recent: true }),
    queryFn: () => api.get<Position[]>(`/api/v1/projects/${projectId}/positions`, { query: { device_id: deviceId, limit: 10, from: new Date(Date.now() - 30 * 86400_000).toISOString() } }),
    enabled: Boolean(projectId),
  });
  const d = device.data;
  const type = types.data?.items.find((t) => t.id === d?.device_type_id);
  if (device.isError) return <Page><div className="text-destructive">{device.error.message}</div></Page>;
  if (!d) return <Page><div className="text-muted-foreground">Loading device…</div></Page>;

  return (
    <>
      <PageHeader
        title={d.name}
        description={type ? `${type.label} (${type.driver_key})` : undefined}
        actions={<>
          <StatusBadge value={d.status} />
          {(d.links ?? []).map((link) => (
            <Button key={link.key} asChild variant="outline" size="sm"><a href={link.url} target="_blank" rel="noreferrer"><ExternalLink className="size-4" /> {link.label}</a></Button>
          ))}
          {user?.is_superuser && <Button asChild variant="outline" size="sm"><Link to={`/admin/devices?device=${d.id}`}>Manage</Link></Button>}
        </>}
      />
      <Page>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Icon iconKey={type?.icon_key} /> Device</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Serial</dt><dd>{d.serial_number ?? "none"}</dd>
                <dt className="text-muted-foreground">Firmware</dt><dd>{d.firmware_version ?? "unknown"}</dd>
                <dt className="text-muted-foreground">Created</dt><dd>{formatTime(d.created_at)}</dd>
                <dt className="text-muted-foreground">Notes</dt><dd>{d.notes ?? ""}</dd>
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>External identities</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {d.external_identities.length === 0 && <div className="text-muted-foreground">No identity yet. Data for this device cannot be received until a DevEUI or provider id is linked.</div>}
              {d.external_identities.map((i) => (
                <div key={i.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{i.external_id}</span>
                  <Badge variant="outline">{i.identity_type}</Badge>
                  <span className="text-muted-foreground">{i.event_count} events, last {formatAgo(i.last_seen_at)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Project assignments</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-sm">
              {d.project_assignments.length === 0 && <div className="text-muted-foreground">Not assigned to a project.</div>}
              {d.project_assignments.map((a) => <div key={a.id}>{formatTime(a.valid_from)} to {a.valid_to ? formatTime(a.valid_to) : "now"}{a.reason ? `, ${a.reason}` : ""}</div>)}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Entity assignments</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-sm">
              {d.entity_assignments.length === 0 && <div className="text-muted-foreground">Not assigned to an entity.</div>}
              {d.entity_assignments.map((a) => <div key={a.id}>Entity <span className="font-mono">{a.entity_id.slice(0, 8)}</span>, {formatTime(a.valid_from)} to {a.valid_to ? formatTime(a.valid_to) : "now"}</div>)}
            </CardContent>
          </Card>
          <div className="lg:col-span-2"><DeviceControl deviceId={d.id} projectId={projectId} canFlush={canAdmin(role) || Boolean(user?.is_superuser)} /></div>
          <WebBleCard deviceId={d.id} deviceName={d.name} driverKey={type?.driver_key} canWrite={canAdmin(role) || Boolean(user?.is_superuser)} />
          <LogFilesCard deviceId={d.id} canWrite={canAdmin(role) || Boolean(user?.is_superuser)} />
          {projectId && (
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Recent positions</CardTitle></CardHeader>
              <CardContent>
                {positions.data?.length === 0 && <div className="text-sm text-muted-foreground">No positions in the last 30 days.</div>}
                <ul className="divide-y text-sm">
                  {positions.data?.map((p) => (
                    <li key={p.id} className="flex flex-wrap items-center gap-3 py-1.5">
                      <span>{formatTime(p.time)}</span>
                      <span className="font-mono text-xs">{(p.geometry?.coordinates as number[])?.[1]?.toFixed(5)}, {(p.geometry?.coordinates as number[])?.[0]?.toFixed(5)}</span>
                      {p.accuracy_m != null && <span className="text-muted-foreground">±{p.accuracy_m} m</span>}
                      <span className="ml-auto flex gap-3">
                        <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setRecord(p.id)}>deliveries</Button>
                        {p.source_event_id != null && (
                          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setEvent({ id: p.source_event_id!, ingestedAt: p.ingested_at })}>provenance</Button>
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
      <SourceEventDialog id={event?.id ?? null} ingestedAt={event?.ingestedAt ?? null} onClose={() => setEvent(null)} />
      <RecordDeliveriesDialog canonicalType="position" canonicalId={record} onClose={() => setRecord(null)} onOpenEvent={(id, ingestedAt) => { setRecord(null); setEvent({ id, ingestedAt }); }} />
    </>
  );
}
