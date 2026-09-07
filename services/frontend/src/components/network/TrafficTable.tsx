import type { ColumnDef } from "@tanstack/react-table";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TrafficRow } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { channelLabel, formatAgo, formatTime, formatTimeShort } from "@/lib/format";

/** The one traffic table (phase 15): the columns follow the row's channel, so a Bluetooth,
 * log file or satellite delivery shows its frame and delivery time where a LoRaWAN uplink shows
 * port, frame counter, spreading factor, signal and gateways. */
export function TrafficTable({ rows, isLoading, emptyMessage, footer, showSource, showIdentity, onSelect }: { rows: TrafficRow[] | undefined; isLoading?: boolean; emptyMessage: string; footer?: ReactNode; showSource?: boolean; showIdentity?: boolean; onSelect: (row: TrafficRow) => void }) {
  const { t } = useTranslation();
  const columns: ColumnDef<TrafficRow, unknown>[] = [
    { header: t("Received"), accessorKey: "ingested_at", cell: ({ getValue }) => <><span className="sm:hidden">{formatTimeShort(getValue<string>())}</span><span className="hidden sm:inline">{formatTime(getValue<string>())}</span></> },
    ...(showSource ? [{ header: t("Source"), accessorKey: "data_source_name" } as ColumnDef<TrafficRow, unknown>] : []),
    ...(showIdentity ? [{ header: t("Identity"), accessorKey: "external_id", cell: ({ row }) => <span className="font-mono text-xs">{row.original.external_id ?? ""}</span> } as ColumnDef<TrafficRow, unknown>] : []),
    { header: t("Device"), accessorKey: "device_name", cell: ({ row }) => row.original.device_name ?? <span className="text-muted-foreground" title={row.original.external_id ?? ""}>{showIdentity ? t("not linked") : (row.original.external_id ?? "")}</span> },
    { header: t("Channel"), accessorKey: "acquisition_channel", cell: ({ row }) => <span>{channelLabel(row.original.acquisition_channel)}<span className="block text-xs text-muted-foreground">{methodLabel(row.original.ingestion_method, t)}</span></span> },
    { header: t("Type"), accessorKey: "event_type" },
    { header: t("Details"), id: "details", accessorFn: (r) => detailsText(r, t), cell: ({ row }) => <Details row={row.original} /> },
    { header: t("Status"), accessorKey: "processing_status", cell: ({ row }) => <span className="inline-flex items-center gap-1"><StatusBadge value={row.original.processing_status} />{row.original.error_code && <span className="text-xs text-destructive">{row.original.error_code}</span>}</span> },
  ];
  return <DataTable columns={columns} data={rows} searchable isLoading={isLoading} emptyMessage={emptyMessage} onRowClick={onSelect} footer={footer} />;
}

type T = (key: string, options?: Record<string, unknown>) => string;

function methodLabel(method: string, t: T): string {
  switch (method) {
    case "webhook": return t("pushed");
    case "mqtt": return "MQTT";
    case "websocket": return t("websocket");
    case "polling": return t("polled");
    case "browser_sync": return t("browser sync");
    case "file_upload": return t("file upload");
    default: return method;
  }
}

/** One line per channel: what a person checks first. */
function detailsText(r: TrafficRow, t: T): string {
  const parts: string[] = [];
  if (r.acquisition_channel === "lorawan") {
    if (r.f_port != null) parts.push(t("port {{port}}", { port: r.f_port }));
    if (r.f_cnt != null) parts.push(t("FCnt {{count}}", { count: r.f_cnt }));
    if (r.spreading_factor != null) parts.push(`SF${r.spreading_factor}`);
    if (r.best_rssi != null) parts.push(`${r.best_rssi.toFixed(0)} dBm${r.best_snr != null ? ` / ${r.best_snr.toFixed(1)} dB` : ""}`);
    if (r.gateway_count) parts.push(t("{{count}} gateways", { count: r.gateway_count }));
  } else {
    if (r.frame_bytes != null) parts.push(t("{{count}} bytes", { count: r.frame_bytes }));
    if (r.delivered_at) parts.push(r.acquisition_channel === "iridium" ? t("delivered {{when}}", { when: formatAgo(r.delivered_at) }) : r.acquisition_channel === "log_file" ? t("uploaded {{when}}", { when: formatAgo(r.delivered_at) }) : t("synced {{when}}", { when: formatAgo(r.delivered_at) }));
    if (r.f_port != null) parts.push(t("port {{port}}", { port: r.f_port }));
  }
  return parts.join(" · ");
}

function Details({ row }: { row: TrafficRow }) {
  const { t } = useTranslation();
  return <span className="text-xs tabular-nums" title={row.delivered_at ? formatTime(row.delivered_at) : undefined}>{detailsText(row, t)}</span>;
}
