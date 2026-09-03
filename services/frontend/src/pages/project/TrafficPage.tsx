import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { TrafficRow } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { SourceEventDialog } from "@/components/devices/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatTime } from "@/lib/format";

const EVENT_TYPES = ["uplink", "join", "status", "downlink_ack", "downlink_transmitted", "log", "location"];

/** LoRaWAN traffic viewer (architecture 8.3). Filters live in the URL. */
export function TrafficPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const eventType = params.get("type") ?? "";
  const hours = Number(params.get("hours") ?? 24);
  const [selected, setSelected] = useState<{ id: number; ingestedAt: string } | null>(null);
  const traffic = useQuery({
    queryKey: queryKeys.traffic(projectId, { eventType, hours }),
    queryFn: () => api.get<TrafficRow[]>(`/api/v1/projects/${projectId}/traffic`, { query: { event_type: eventType || undefined, from: new Date(Date.now() - hours * 3600_000).toISOString(), limit: 200 } }),
    refetchInterval: 15_000,
  });

  const columns: ColumnDef<TrafficRow, unknown>[] = [
    { header: "Time", accessorKey: "ingested_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: "Device", accessorKey: "device_name", cell: ({ row }) => <span title={row.original.external_id ?? ""}>{row.original.device_name}</span> },
    { header: "Type", accessorKey: "event_type" },
    { header: "Port", accessorKey: "f_port" },
    { header: "FCnt", accessorKey: "f_cnt" },
    { header: "SF", accessorKey: "spreading_factor" },
    { header: "RSSI", accessorKey: "best_rssi", cell: ({ getValue }) => getValue<number | null>()?.toFixed(0) ?? "" },
    { header: "SNR", accessorKey: "best_snr", cell: ({ getValue }) => getValue<number | null>()?.toFixed(1) ?? "" },
    { header: "Gateways", accessorKey: "gateway_count" },
    { header: "Source", accessorKey: "data_source_name" },
    { header: "Status", accessorKey: "processing_status", cell: ({ row }) => <span className="inline-flex items-center gap-1"><StatusBadge value={row.original.processing_status} />{row.original.error_code && <span className="text-xs text-destructive">{row.original.error_code}</span>}</span> },
  ];

  return (
    <>
      <PageHeader
        title="LoRaWAN traffic"
        description="Every message received for this project's devices, with raw payload, decode result, gateway receptions and trace"
        actions={<>
          <Select value={eventType || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("type"); else p.set("type", v); return p; })}>
            <SelectTrigger className="w-44"><SelectValue placeholder="All types" /></SelectTrigger>
            <SelectContent><SelectItem value="all">All types</SelectItem>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
          </Select>
          <Input type="number" min={1} max={720} className="w-24" value={hours} onChange={(e) => setParams((p) => { p.set("hours", e.target.value); return p; })} aria-label="Hours back" />
          <Button variant="outline" size="icon" onClick={() => traffic.refetch()} aria-label="Refresh"><RefreshCw className="size-4" /></Button>
        </>}
      />
      <Page>
        <DataTable columns={columns} data={traffic.data} isLoading={traffic.isPending} emptyMessage="No traffic in this window." onRowClick={(r) => setSelected({ id: r.source_event_id, ingestedAt: r.ingested_at })} footer={traffic.data && `${traffic.data.length} messages, last ${hours} hours`} />
      </Page>
      <SourceEventDialog id={selected?.id ?? null} ingestedAt={selected?.ingestedAt ?? null} onClose={() => setSelected(null)} />
    </>
  );
}
