import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ExternalLink, MapPin, Pencil, RadioTower } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { GatewayDay, GatewayDetail, TrafficRow } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { JsonView } from "@/components/common/JsonView";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DeviceTraffic } from "@/components/devices/DeviceTraffic";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { MiniMap } from "@/components/map/MiniMap";
import { GatewayCoverageMap } from "@/components/network/GatewayCoverageMap";
import { GatewayDaysChart } from "@/components/network/GatewayDaysChart";
import { GatewayLocationDialog } from "@/components/network/GatewayLocationDialog";
import { GatewayNameDialog } from "@/components/network/GatewayNameDialog";
import { WindowSelect } from "@/components/network/WindowSelect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import { useTab } from "@/hooks/useTab";
import { COVERAGE_PERIODS, periodLabel } from "@/lib/coverage";
import { formatAgo, formatTime } from "@/lib/format";
import {
  gatewayCoords,
  isOffloadStation,
  isRelay,
  locationSourceLabel,
  rangeLabel,
} from "@/lib/gateways";
import { isAllProjects } from "@/lib/scope";

/** The Overview's figures cover the last 30 days, as the Gateways list does. */
const HOURS = 24 * 30;
const TABS = ["overview", "coverage", "traffic"] as const;

const signal = (rssi: number | null | undefined, snr: number | null | undefined) =>
  rssi == null && snr == null ? "" : `${rssi ?? "?"} dBm / ${snr ?? "?"} dB`;

/**
 * A gateway's own page (decision D369, Tim, 2026-11-06: a real page like the device and
 * entity pages, so it can carry more than the list's dialog did): Overview with its status,
 * times, source, location and the devices it heard; Coverage with the positions it heard and
 * their paths on a map; Traffic with its receptions per day and the messages it relayed.
 */
export function GatewayPage() {
  const { t } = useTranslation();
  const now = useNow();
  const { projectId = "", gatewayId = "" } = useParams();
  const allProjects = isAllProjects(projectId);
  const { can } = usePermissions(allProjects ? undefined : projectId);
  const [tab, setTab] = useTab(TABS);
  const [renaming, setRenaming] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [coverageHours, setCoverageHours] = useState(168);
  const [daysHours, setDaysHours] = useState(HOURS);
  const [sourceEvent, setSourceEvent] = useState<{ id: number; ingestedAt: string } | null>(
    null,
  );
  const base = `/api/v1/projects/${projectId}`;
  const detail = useQuery({
    queryKey: queryKeys.gateway(projectId, gatewayId, HOURS),
    queryFn: () =>
      api.get<GatewayDetail>(`${base}/gateways/${gatewayId}`, { query: { hours: HOURS } }),
    refetchInterval: 60_000,
  });
  const days = useQuery({
    queryKey: queryKeys.gatewayDays(projectId, gatewayId, daysHours),
    queryFn: () =>
      api.get<GatewayDay[]>(`${base}/gateways/${gatewayId}/days`, {
        query: { hours: daysHours },
      }),
    enabled: tab === "traffic",
  });
  const g = detail.data?.gateway;
  const heard = detail.data?.devices ?? [];
  if (detail.isError)
    return (
      <Page>
        <Callout kind="error">{detail.error.message}</Callout>
      </Page>
    );
  if (!g) return <Page>{t("Loading…")}</Page>;
  const coordinates = (g.geometry as { coordinates?: [number, number] } | null)?.coordinates;
  // a gateway the platform's list does not carry: known from the uplinks it relayed alone, so
  // its name and its own status reports never reach Protect (D370)
  const fromUplinksOnly = !g.name && g.location_source !== "platform";
  const canEdit = can("project:write") && !allProjects;
  return (
    <>
      <PageHeader
        title={g.display_name}
        description={`${g.data_source_name ?? ""} · ${g.external_id}`}
        leading={
          <span className="flex size-12 shrink-0 items-center justify-center rounded-md border text-primary">
            <RadioTower className="size-6" />
          </span>
        }
        actions={
          <>
            <StatusBadge value={g.status} />
            {isRelay(g) && <Badge variant="outline">{t("Relay (mesh)")}</Badge>}
            {isOffloadStation(g) && <Badge variant="outline">{t("Offload station")}</Badge>}
            {g.device_id && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/projects/${projectId}/devices/${g.device_id}`}>
                  {t("Offload station device")}
                </Link>
              </Button>
            )}
            {coordinates && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/projects/${projectId}/map?gateway=${g.id}`}>
                  <MapPin className="size-4" /> {t("Show on live map")}
                </Link>
              </Button>
            )}
            {(g.links ?? []).map((l) => (
              <Button key={l.key} asChild variant="outline" size="sm">
                <a href={l.url} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-4" /> {l.label}
                </a>
              </Button>
            ))}
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setRenaming(true)}>
                <Pencil className="size-4" /> {t("Rename")}
              </Button>
            )}
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setPlacing(true)}>
                <MapPin className="size-4" />{" "}
                {coordinates ? t("Change location") : t("Set location")}
              </Button>
            )}
          </>
        }
      />
      <Page>
        <Tabs value={tab} onValueChange={(v) => setTab(v as (typeof TABS)[number])}>
          <TabsList className="max-w-full justify-start overflow-x-auto overflow-y-hidden [scrollbar-width:none] sm:overflow-visible">
            <TabsTrigger value="overview">{t("Overview")}</TabsTrigger>
            <TabsTrigger value="coverage">{t("Coverage")}</TabsTrigger>
            <TabsTrigger value="traffic">{t("Traffic")}</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <RadioTower className="size-4" /> {t("Gateway")}
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-sm">
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                    <dt className="text-muted-foreground">{t("Status")}</dt>
                    <dd>
                      <StatusBadge value={g.status} />
                      {g.status === "silent" && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {t("nothing heard from it for more than a day")}
                        </span>
                      )}
                    </dd>
                    <dt className="text-muted-foreground">{t("Last seen")}</dt>
                    <dd title={formatTime(g.last_seen_at)}>
                      {g.last_seen_at ? formatAgo(g.last_seen_at, now) : t("never")}
                    </dd>
                    <dt className="text-muted-foreground">{t("Last reception")}</dt>
                    <dd title={formatTime(g.last_reception_at)}>
                      {g.last_reception_at
                        ? formatAgo(g.last_reception_at, now)
                        : t("none in 30 days")}
                    </dd>
                    <dt className="text-muted-foreground">{t("First seen")}</dt>
                    <dd>{g.first_seen_at ? formatTime(g.first_seen_at) : t("unknown")}</dd>
                    <dt className="text-muted-foreground">{t("Last 30 days")}</dt>
                    <dd>
                      {t("{{count}} receptions", { count: g.receptions })}
                      {", "}
                      {t("{{count}} devices", { count: g.devices })}
                      {signal(g.mean_rssi, g.mean_snr) && `, ${signal(g.mean_rssi, g.mean_snr)}`}
                    </dd>
                    {rangeLabel(g, t) && (
                      <>
                        <dt className="text-muted-foreground">{t("Range")}</dt>
                        <dd
                          title={t(
                            "The shortest, longest and mean distance from the positions it heard in the window to the gateway",
                          )}
                        >
                          {rangeLabel(g, t)}
                          {", "}
                          {t("{{count}} positions", { count: g.range_positions })}
                        </dd>
                      </>
                    )}
                    <dt className="text-muted-foreground">{t("Source")}</dt>
                    <dd>{g.data_source_name ?? g.data_source_id}</dd>
                    <dt className="text-muted-foreground">{t("Gateway id")}</dt>
                    <dd className="font-mono text-xs">{g.external_id}</dd>
                    {g.description && (
                      <>
                        <dt className="text-muted-foreground">{t("Description")}</dt>
                        <dd>{g.description}</dd>
                      </>
                    )}
                  </dl>
                  {fromUplinksOnly && (
                    <p className="mt-3 text-xs text-muted-foreground">
                      {t(
                        "Known from the uplinks it relayed alone: the network's gateway list does not carry it, so its name and its own status reports do not reach Protect. Its status follows its receptions.",
                      )}
                    </p>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <MapPin className="size-4" /> {t("Location")}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {coordinates ? (
                    <>
                      <div className="font-mono text-xs">
                        {gatewayCoords(g)}
                        {g.altitude_m != null ? `, ${g.altitude_m} m` : ""}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {g.location_source &&
                          t("from {{source}}", {
                            source: locationSourceLabel(g.location_source, t),
                          })}
                        {g.location_at && `, ${formatTime(g.location_at)}`}
                      </div>
                      <div className="h-56">
                        <MiniMap
                          point={coordinates}
                          to={`/projects/${projectId}/map?gateway=${g.id}`}
                        />
                      </div>
                    </>
                  ) : (
                    <p className="text-muted-foreground">
                      {t(
                        "No location known: the network reported none, so the map cannot place this gateway.",
                      )}
                    </p>
                  )}
                </CardContent>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle>{t("Devices heard in the last 30 days")}</CardTitle>
                </CardHeader>
                <CardContent>
                  {heard.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {t("Heard none of the project's devices in the last 30 days")}
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-muted-foreground">
                            <th className="py-1 pr-3">{t("Device")}</th>
                            <th className="pr-3">{t("Receptions")}</th>
                            <th className="pr-3">{t("Mean signal")}</th>
                            <th>{t("Last reception")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {heard.map((d) => (
                            <tr key={d.device_id ?? "none"} className="border-t">
                              <td className="py-1 pr-3">
                                {d.device_id ? (
                                  <Link
                                    className="underline"
                                    to={`/projects/${projectId}/devices/${d.device_id}`}
                                  >
                                    {d.device_name ?? d.device_id}
                                  </Link>
                                ) : (
                                  t("unknown device")
                                )}
                              </td>
                              <td className="pr-3">{d.receptions}</td>
                              <td className="pr-3">{signal(d.mean_rssi, d.mean_snr)}</td>
                              <td title={formatTime(d.last_reception_at)}>
                                {formatAgo(d.last_reception_at, now)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
              {Object.keys(g.stats).length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>
                      {t("Statistics")}{" "}
                      {g.last_stats_at && (
                        <span className="text-sm font-normal text-muted-foreground">
                          {formatAgo(g.last_stats_at, now)}
                        </span>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <JsonView value={g.stats} />
                  </CardContent>
                </Card>
              )}
              {Object.keys(g.attributes).length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>{t("Provider diagnostics")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <JsonView value={g.attributes} />
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
          <TabsContent value="coverage">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={String(coverageHours)}
                  onValueChange={(v) => setCoverageHours(Number(v))}
                >
                  <SelectTrigger className="w-40" aria-label={t("Period")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COVERAGE_PERIODS.map((hours) => (
                      <SelectItem key={hours} value={String(hours)}>
                        {periodLabel(hours, t)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-xs text-muted-foreground">
                  {t(
                    "Where the project's devices were when this gateway heard them, coloured by signal from red (weak) to green (strong), with a line from each position to the gateway.",
                  )}
                </span>
              </div>
              <GatewayCoverageMap projectId={projectId} gateway={g} hours={coverageHours} />
            </div>
          </TabsContent>
          <TabsContent value="traffic">
            <div className="space-y-4">
              <Card>
                <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
                  <CardTitle>{t("Receptions per day")}</CardTitle>
                  <WindowSelect hours={daysHours} onChange={setDaysHours} className="w-40" />
                </CardHeader>
                <CardContent>
                  {days.isError ? (
                    <Callout kind="error">{days.error.message}</Callout>
                  ) : days.data ? (
                    days.data.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {t("This gateway relayed none of the project's messages in the window.")}
                      </p>
                    ) : (
                      <GatewayDaysChart days={days.data} hours={daysHours} />
                    )
                  ) : (
                    <p className="text-sm text-muted-foreground">{t("Loading…")}</p>
                  )}
                </CardContent>
              </Card>
              <DeviceTraffic
                projectId={projectId}
                gatewayId={g.id}
                onSelect={(r: TrafficRow) =>
                  setSourceEvent({ id: r.source_event_id, ingestedAt: r.ingested_at })
                }
              />
            </div>
          </TabsContent>
        </Tabs>
      </Page>
      <GatewayNameDialog
        key={`name-${renaming ? g.id : "none"}`}
        projectId={projectId}
        gateway={renaming ? g : null}
        onClose={() => setRenaming(false)}
      />
      <GatewayLocationDialog
        key={`place-${placing ? g.id : "none"}`}
        projectId={projectId}
        gateway={placing ? g : null}
        onClose={() => setPlacing(false)}
      />
      <SourceEventDialog
        id={sourceEvent?.id ?? null}
        ingestedAt={sourceEvent?.ingestedAt ?? null}
        onClose={() => setSourceEvent(null)}
      />
    </>
  );
}
