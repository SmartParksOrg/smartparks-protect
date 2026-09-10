import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceConnectivityRead, SourceConnectivity } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useNow } from "@/hooks/useNow";
import { formatAgo, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The periods the cards summarise, in hours. */
const PERIODS = [24, 168, 720, 2160];

/** How each network the device is reachable through performs (architecture 20, decision D161):
 * one card per data source, the connection state and the last contacts first, then what the
 * network kind knows: gateways and signal for LoRaWAN, sessions and estimates for Iridium.
 * Apart from the health card, which is the device's own status. */
export function ConnectivityCards({
  deviceId,
  projectId,
  hours,
  onHoursChange,
}: {
  deviceId: string;
  projectId?: string;
  hours: number;
  onHoursChange: (hours: number) => void;
}) {
  const { t } = useTranslation();
  const connectivity = useQuery({
    queryKey: queryKeys.deviceConnectivity(deviceId, hours),
    queryFn: () =>
      api.get<DeviceConnectivityRead>(
        `/api/v1/devices/${deviceId}/connectivity`,
        {
          query: { hours },
        },
      ),
    refetchInterval: 60_000,
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">{t("Period")}</span>
        <Select
          value={String(hours)}
          onValueChange={(v) => onHoursChange(Number(v))}
        >
          <SelectTrigger className="h-8 w-32" aria-label={t("Period")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((h) => (
              <SelectItem key={h} value={String(h)}>
                {periodLabel(h, t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {connectivity.isError && (
        <Callout kind="error">
          {t("Could not load the connectivity: {{message}}", {
            message: connectivity.error.message,
          })}
        </Callout>
      )}
      {connectivity.data && connectivity.data.sources.length === 0 && (
        <Callout kind="info">
          {t(
            "This device has no identity on any data source yet, so no network has carried its data.",
          )}
        </Callout>
      )}
      <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        {(connectivity.data?.sources ?? []).map((source) => (
          <SourceCard
            key={source.data_source_id}
            source={source}
            projectId={projectId}
            hours={hours}
          />
        ))}
      </div>
    </div>
  );
}

function periodLabel(
  hours: number,
  t: (key: string, o?: Record<string, unknown>) => string,
): string {
  if (hours < 48) return t("{{count}} hours", { count: hours });
  return t("{{count}} days", { count: Math.round(hours / 24) });
}

const statusClass: Record<string, string> = {
  online: "bg-brand-green-light",
  silent: "bg-brand-sand",
  unknown: "bg-muted-foreground/40",
};

function SourceCard({
  source,
  projectId,
  hours,
}: {
  source: SourceConnectivity;
  projectId?: string;
  hours: number;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const statusLabel =
    source.status === "online"
      ? t("online")
      : source.status === "silent"
        ? t("silent")
        : t("unknown");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span
            className={cn(
              "inline-block size-2.5 rounded-full",
              statusClass[source.status] ?? "",
            )}
            aria-label={statusLabel}
            title={statusLabel}
          />
          {source.data_source_name}
          <span className="text-xs font-normal text-muted-foreground">
            {channelLabel(source.channel, t)}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <Row label={t("Connection")} value={statusLabel} />
          <Row
            label={t("Last contact")}
            value={formatAgo(source.last_contact_at, now)}
            title={formatTime(source.last_contact_at)}
          />
          {source.last_uplink_at && (
            <Row
              label={t("Last uplink")}
              value={formatAgo(source.last_uplink_at, now)}
              title={formatTime(source.last_uplink_at)}
            />
          )}
          {source.last_join_at && (
            <Row
              label={t("Last join")}
              value={formatAgo(source.last_join_at, now)}
              title={formatTime(source.last_join_at)}
            />
          )}
          {source.last_downlink_at && (
            <Row
              label={t("Last downlink")}
              value={formatAgo(source.last_downlink_at, now)}
              title={formatTime(source.last_downlink_at)}
            />
          )}
          {source.lorawan && (
            <LoRaWANRows
              link={source.lorawan}
              source={source}
              projectId={projectId}
              hours={hours}
            />
          )}
          {source.iridium && (
            <IridiumRows link={source.iridium} hours={hours} />
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

function Row({
  label,
  value,
  title,
  muted,
}: {
  label: string;
  value: string | null | undefined;
  title?: string;
  muted?: boolean;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn(muted ? "text-muted-foreground" : "")} title={title}>
        {value ?? ""}
      </dd>
    </>
  );
}

function channelLabel(channel: string, t: (key: string) => string): string {
  switch (channel) {
    case "lorawan":
      return t("LoRaWAN");
    case "iridium":
      return t("Iridium");
    case "webble":
      return t("Bluetooth");
    case "log_file":
      return t("log files");
    default:
      return channel;
  }
}

function LoRaWANRows({
  link,
  source,
  projectId,
  hours,
}: {
  link: NonNullable<SourceConnectivity["lorawan"]>;
  source: SourceConnectivity;
  projectId?: string;
  hours: number;
}) {
  const { t } = useTranslation();
  const period = periodLabel(hours, t);
  return (
    <>
      {source.last_rssi != null && (
        <Row
          label={t("Last signal")}
          value={`${source.last_rssi.toFixed(0)} dBm${source.last_snr != null ? ` / ${source.last_snr.toFixed(1)} dB` : ""}`}
        />
      )}
      <Row
        label={t("Uplinks heard, {{period}}", { period })}
        value={String(link.uplinks)}
      />
      <Row
        label={t("Missed frames")}
        value={
          link.frames_seen > 1
            ? t("{{missed}} of {{total}}", {
                missed: link.missed_frames,
                total: link.frames_seen + link.missed_frames,
              })
            : t("not enough frames yet")
        }
        muted={link.frames_seen <= 1}
      />
      <Row
        label={t("Gateways")}
        value={
          link.gateway_count ? String(link.gateway_count) : t("none heard")
        }
        muted={!link.gateway_count}
      />
      {link.best_gateway_name && (
        <>
          <dt className="text-muted-foreground">{t("Best gateway")}</dt>
          <dd>
            {projectId && link.best_gateway_id ? (
              <Link
                className="underline"
                to={`/projects/${projectId}/network/gateways?gateway=${link.best_gateway_id}`}
              >
                {link.best_gateway_name}
              </Link>
            ) : (
              link.best_gateway_name
            )}
            {link.best_gateway_share != null &&
              ` · ${t("{{share}}% of uplinks", { share: Math.round(link.best_gateway_share * 100) })}`}
          </dd>
        </>
      )}
      {link.mean_rssi != null && (
        <Row
          label={t("Mean signal")}
          value={`${link.mean_rssi.toFixed(0)} dBm${link.mean_snr != null ? ` / ${link.mean_snr.toFixed(1)} dB` : ""}`}
        />
      )}
    </>
  );
}

function IridiumRows({
  link,
  hours,
}: {
  link: NonNullable<SourceConnectivity["iridium"]>;
  hours: number;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const period = periodLabel(hours, t);
  const last = link.last_session as
    | {
        status?: string;
        status_text?: string;
        sequence?: number | null;
        session_at?: string | null;
        latitude?: number | null;
        longitude?: number | null;
        cep_km?: number | null;
        bytes?: number;
        missed_since_last?: number | null;
      }
    | null
    | undefined;
  const estimate =
    last && last.latitude != null && last.longitude != null
      ? `${last.latitude.toFixed(4)}, ${last.longitude.toFixed(4)}${last.cep_km != null ? ` ±${last.cep_km} km` : ""}`
      : null;
  return (
    <>
      {last && (
        <>
          <Row
            label={t("Last session")}
            value={last.session_at ? formatAgo(last.session_at, now) : ""}
            title={last.session_at ? formatTime(last.session_at) : undefined}
          />
          <Row
            label={t("Outcome")}
            value={last.status_text ?? last.status ?? ""}
            muted={last.status !== "ok"}
          />
          {last.sequence != null && (
            <Row label={t("Session counter")} value={String(last.sequence)} />
          )}
          {estimate && (
            <Row
              label={t("Network estimate")}
              value={
                last.status === "location_unacceptable"
                  ? `${estimate} (${t("poor")})`
                  : estimate
              }
              muted={last.status === "location_unacceptable"}
            />
          )}
        </>
      )}
      <Row
        label={t("Sessions, {{period}}", { period })}
        value={String(link.sessions)}
      />
      <Row
        label={t("Bytes, {{period}}", { period })}
        value={String(link.bytes)}
      />
      <Row
        label={t("Missed sessions")}
        value={String(link.missed)}
        muted={link.missed === 0}
      />
      {link.duplicates > 0 && (
        <Row label={t("Redeliveries")} value={String(link.duplicates)} />
      )}
    </>
  );
}
