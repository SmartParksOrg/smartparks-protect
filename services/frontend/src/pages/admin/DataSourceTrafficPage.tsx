import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, TrafficRow } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { TrafficTable } from "@/components/network/TrafficTable";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const EVENT_TYPES = ["uplink", "join", "status", "downlink_ack", "downlink_transmitted", "log", "location", "gateway_receptions"];

/** What one data source receives, linked to a device or not: the administrator's window while
 * connecting a platform (server admin). Refreshes every five seconds. */
export function DataSourceTrafficPage() {
  const { t } = useTranslation();
  const { sourceId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const eventType = params.get("type") ?? "";
  const hours = Number(params.get("hours") ?? 24);
  const identity = params.get("identity") ?? "";
  const [selected, setSelected] = useState<{ id: number; ingestedAt: string } | null>(null);
  const source = useQuery({ queryKey: queryKeys.dataSource(sourceId), queryFn: () => api.get<DataSource>(`/api/v1/data-sources/${sourceId}`) });
  const traffic = useQuery({
    queryKey: queryKeys.sourceTraffic(sourceId, { eventType, hours, identity }),
    queryFn: () => api.get<TrafficRow[]>(`/api/v1/data-sources/${sourceId}/traffic`, { query: { event_type: eventType || undefined, external_id: identity || undefined, from: new Date(Date.now() - hours * 3600_000).toISOString(), limit: 200 } }),
    refetchInterval: 5_000,
  });


  return (
    <>
      <PageHeader
        title={source.data ? t("Traffic of {{name}}", { name: source.data.name }) : t("Data source traffic")}
        description={t("Every message this source received, linked to a device or not, with the raw payload and the trace. Refreshes every five seconds.")}
        actions={<>
          <Button asChild variant="outline"><Link to="/admin/data-sources"><ArrowLeft className="size-4" /> {t("Data sources")}</Link></Button>
          <Input className="w-44 font-mono" placeholder={t("Identity contains")} value={identity} onChange={(e) => setParams((p) => { if (e.target.value) p.set("identity", e.target.value); else p.delete("identity"); return p; })} aria-label={t("Identity filter")} />
          <Select value={eventType || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("type"); else p.set("type", v); return p; })}>
            <SelectTrigger className="w-44"><SelectValue placeholder={t("All types")} /></SelectTrigger>
            <SelectContent><SelectItem value="all">{t("All types")}</SelectItem>{EVENT_TYPES.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}</SelectContent>
          </Select>
          <Input type="number" min={1} max={720} className="w-24" value={hours} onChange={(e) => setParams((p) => { p.set("hours", e.target.value); return p; })} aria-label={t("Hours back")} />
          <Button variant="outline" size="icon" onClick={() => traffic.refetch()} aria-label={t("Refresh")}><RefreshCw className="size-4" /></Button>
        </>}
      />
      <Page>
        <TrafficTable showIdentity rows={traffic.data} isLoading={traffic.isPending} emptyMessage={t("Nothing received in this window. The platform's own log says whether it posted.")} onSelect={(r) => setSelected({ id: r.source_event_id, ingestedAt: r.ingested_at })} footer={traffic.data && t("{{count}} messages, last {{hours}} hours", { count: traffic.data.length, hours })} />
      </Page>
      <SourceEventDialog id={selected?.id ?? null} ingestedAt={selected?.ingestedAt ?? null} onClose={() => setSelected(null)} />
    </>
  );
}
