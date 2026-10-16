import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link, useParams } from "react-router";
import { HardDrive } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  OffloadOverview,
  OffloadOverviewStation,
  OffloadOverviewTracker,
  OffloadUnknownAddress,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Badge } from "@/components/ui/badge";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";

/**
 * The project's LP0 network on one page (phase 42, Tim, 2026-10-16): every offload station
 * with what its cards brought and its own last report, every tracker with an LP0 address or
 * frames (the keys stay on the device page, behind Show), and the addresses the stations
 * received that no device has. The page lists and links; everything is set on the device
 * pages, so a station or a tracker is a link away. Figures cover the last 30 days, as on the
 * Gateways page.
 */
export function OffloadPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const now = useNow();
  const { all: serverAdmin } = usePermissions(projectId);
  const overview = useQuery({
    queryKey: queryKeys.projectOffload(projectId),
    queryFn: () =>
      api.get<OffloadOverview>(`/api/v1/projects/${projectId}/offload`),
    refetchInterval: 60_000,
  });
  const data = overview.data;
  const devicePath = (id: string) => `/projects/${projectId}/devices/${id}`;
  const entityPath = (id: string) => `/projects/${projectId}/entities/${id}`;
  const yesNo = (value: boolean | null | undefined) =>
    value == null ? t("unknown") : value ? t("yes") : t("no");
  const ago = (value: string | null | undefined) =>
    value ? (
      <span title={formatTime(value)}>{formatAgo(value, now)}</span>
    ) : (
      <span className="text-muted-foreground">{t("none in 30 days")}</span>
    );

  const stationColumns: ColumnDef<OffloadOverviewStation, unknown>[] = [
    {
      header: t("Station"),
      accessorKey: "device_name",
      cell: ({ row }) => (
        <span>
          <Link
            className="font-medium underline"
            to={devicePath(row.original.device_id)}
          >
            {row.original.device_name}
          </Link>
          {row.original.entity_id && row.original.entity_name && (
            <Link
              className="ml-2 text-xs underline"
              to={entityPath(row.original.entity_id)}
            >
              {row.original.entity_name}
            </Link>
          )}
          {row.original.station_eui && (
            <span className="ml-2 font-mono text-xs text-muted-foreground">
              {row.original.station_eui}
            </span>
          )}
        </span>
      ),
    },
    {
      header: t("Cards"),
      accessorKey: "files",
      cell: ({ row }) =>
        row.original.files > 0 ? (
          <span title={formatTime(row.original.last_upload_at)}>
            {t("{{files}} files, {{frames}} frames", {
              files: row.original.files,
              frames: row.original.frames,
            })}
            {row.original.frames_retained > 0 && (
              <span className="ml-1 text-muted-foreground">
                {t("({{count}} of unknown trackers)", {
                  count: row.original.frames_retained,
                })}
              </span>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">{t("none yet")}</span>
        ),
    },
    {
      header: t("Last upload"),
      accessorKey: "last_upload_at",
      cell: ({ getValue }) => {
        const value = getValue<string | null>();
        return value ? (
          <span title={formatTime(value)}>{formatAgo(value, now)}</span>
        ) : (
          <span className="text-muted-foreground">{t("never")}</span>
        );
      },
    },
    {
      header: t("Received"),
      accessorKey: "receptions",
      cell: ({ row }) =>
        row.original.receptions > 0
          ? t("{{frames}} frames of {{trackers}} trackers", {
              frames: row.original.receptions,
              trackers: row.original.trackers,
            })
          : "",
    },
    {
      header: t("Last offload"),
      accessorKey: "last_reception_at",
      cell: ({ getValue }) => ago(getValue<string | null>()),
    },
    {
      header: t("Own report"),
      id: "report",
      cell: ({ row }) =>
        row.original.state_time ? (
          <span
            title={t("The station's own report, {{ago}}", {
              ago: formatAgo(row.original.state_time, now),
            })}
          >
            {t("card {{ok}}", { ok: yesNo(row.original.card_ok) })}
            {", "}
            {t("listening {{ok}}", { ok: yesNo(row.original.listening) })}
            {row.original.storage_pending != null &&
              row.original.storage_pending > 0 &&
              `, ${t("{{count}} pending", { count: row.original.storage_pending })}`}
            {row.original.visits_complete != null &&
              `, ${t("{{count}} visits", { count: row.original.visits_complete })}`}
          </span>
        ) : (
          <span className="text-muted-foreground">{t("none")}</span>
        ),
    },
    {
      header: t("Place"),
      accessorKey: "has_location",
      cell: ({ row }) =>
        row.original.has_location ? (
          t("set")
        ) : (
          <Link
            className="text-destructive underline"
            to={devicePath(row.original.device_id)}
            title={t(
              "A station does not move: set its place by hand on its device page",
            )}
          >
            {t("not set")}
          </Link>
        ),
    },
  ];

  const trackerColumns: ColumnDef<OffloadOverviewTracker, unknown>[] = [
    {
      header: t("Tracker"),
      accessorKey: "device_name",
      cell: ({ row }) => (
        <span>
          <Link
            className="font-medium underline"
            to={devicePath(row.original.device_id)}
          >
            {row.original.device_name}
          </Link>
          {row.original.entity_id && row.original.entity_name && (
            <Link
              className="ml-2 text-xs underline"
              to={entityPath(row.original.entity_id)}
            >
              {row.original.entity_name}
            </Link>
          )}
        </span>
      ),
    },
    {
      header: t("LP0 address"),
      accessorKey: "dev_addr",
      cell: ({ row }) => (
        <span>
          {row.original.dev_addr ? (
            <span className="font-mono">{row.original.dev_addr}</span>
          ) : (
            <Link
              className="text-destructive underline"
              to={devicePath(row.original.device_id)}
            >
              {t("not set")}
            </Link>
          )}
          {row.original.reported_dev_addr &&
            row.original.reported_dev_addr !== row.original.dev_addr && (
              <Badge
                variant="outline"
                className="ml-2 align-middle"
                title={t(
                  "The device itself reports another address in its settings; check which is provisioned",
                )}
              >
                {t("device says {{addr}}", {
                  addr: row.original.reported_dev_addr,
                })}
              </Badge>
            )}
        </span>
      ),
    },
    {
      header: t("Keys"),
      accessorKey: "keys_set",
      cell: ({ row }) =>
        row.original.keys_set ? (
          <span title={formatTime(row.original.set_at)}>
            {row.original.source === "device"
              ? t("from the device, {{ago}}", {
                  ago: formatAgo(row.original.set_at, now),
                })
              : t("set {{ago}}", { ago: formatAgo(row.original.set_at, now) })}
          </span>
        ) : (
          <span className="text-destructive">{t("not set")}</span>
        ),
    },
    {
      header: t("Offloaded"),
      accessorKey: "receptions",
      cell: ({ row }) =>
        row.original.receptions > 0
          ? t("{{frames}} frames at {{stations}} stations", {
              frames: row.original.receptions,
              stations: row.original.stations,
            })
          : "",
    },
    {
      header: t("Last offload"),
      accessorKey: "last_reception_at",
      cell: ({ row }) => (
        <span>
          {ago(row.original.last_reception_at)}
          {row.original.last_station_name && (
            <span className="ml-1 text-xs text-muted-foreground">
              {t("at")}{" "}
              {row.original.last_station_device_id ? (
                <Link
                  className="underline"
                  to={devicePath(row.original.last_station_device_id)}
                >
                  {row.original.last_station_name}
                </Link>
              ) : (
                row.original.last_station_name
              )}
            </span>
          )}
        </span>
      ),
    },
    {
      header: t("Counter"),
      accessorKey: "last_f_cnt",
      cell: ({ row }) =>
        row.original.last_f_cnt != null ? (
          <span
            className="font-mono"
            title={
              row.original.last_frame_at
                ? t(
                    "The last frame verified under the device's keys, {{ago}}",
                    {
                      ago: formatAgo(row.original.last_frame_at, now),
                    },
                  )
                : undefined
            }
          >
            {row.original.last_f_cnt}
          </span>
        ) : (
          ""
        ),
    },
  ];

  const unknownColumns: ColumnDef<OffloadUnknownAddress, unknown>[] = [
    {
      header: t("LP0 address"),
      accessorKey: "dev_addr",
      cell: ({ getValue }) => (
        <span className="font-mono">{getValue<string>()}</span>
      ),
    },
    {
      header: t("Tracker EUI"),
      accessorKey: "dev_eui",
      cell: ({ getValue }) => (
        <span className="font-mono">{getValue<string | null>() ?? ""}</span>
      ),
    },
    { header: t("Frames"), accessorKey: "receptions" },
    {
      header: t("First seen"),
      accessorKey: "first_seen_at",
      cell: ({ getValue }) => ago(getValue<string | null>()),
    },
    {
      header: t("Last seen"),
      accessorKey: "last_seen_at",
      cell: ({ getValue }) => ago(getValue<string | null>()),
    },
  ];

  const stations = data?.stations ?? [];
  const trackers = data?.trackers ?? [];
  const unknown = data?.unknown ?? [];
  return (
    <>
      <PageHeader
        title={t("Offload")}
        description={t(
          "The LP0 network: the offload stations, the trackers they serve and the addresses no device has. Figures cover the last {{days}} days.",
          { days: data?.window_days ?? 30 },
        )}
      />
      <Page>
        {overview.error && (
          <Callout kind="error">{overview.error.message}</Callout>
        )}
        <section className="space-y-2">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <HardDrive className="size-4" /> {t("Stations")}
          </h2>
          <DataTable
            columns={stationColumns}
            data={data ? stations : undefined}
            isLoading={overview.isPending}
            defaultHiddenSmall={["last_upload_at", "report", "has_location"]}
            cardOf={(s) => (
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    className="font-medium underline"
                    to={devicePath(s.device_id)}
                  >
                    {s.device_name}
                  </Link>
                  {s.entity_id && s.entity_name && (
                    <Link
                      className="text-xs underline"
                      to={entityPath(s.entity_id)}
                    >
                      {s.entity_name}
                    </Link>
                  )}
                  {!s.has_location && (
                    <Badge variant="outline" className="text-destructive">
                      {t("no place")}
                    </Badge>
                  )}
                </div>
                {s.station_eui && (
                  <div className="font-mono text-xs text-muted-foreground">
                    {s.station_eui}
                  </div>
                )}
                <div className="text-xs">
                  {s.files > 0
                    ? t("{{files}} files, {{frames}} frames", {
                        files: s.files,
                        frames: s.frames,
                      }) +
                      t(", last uploaded {{ago}}", {
                        ago: formatAgo(s.last_upload_at, now),
                      })
                    : t("No card uploaded yet")}
                </div>
                <div className="text-xs">
                  {s.receptions > 0
                    ? t("{{frames}} frames of {{trackers}} trackers", {
                        frames: s.receptions,
                        trackers: s.trackers,
                      }) + `, ${formatAgo(s.last_reception_at, now)}`
                    : t("No offload in 30 days")}
                </div>
                {s.state_time && (
                  <div className="text-xs text-muted-foreground">
                    {t("card {{ok}}", { ok: yesNo(s.card_ok) })}
                    {", "}
                    {t("listening {{ok}}", { ok: yesNo(s.listening) })}
                    {", "}
                    {formatAgo(s.state_time, now)}
                  </div>
                )}
              </div>
            )}
            emptyMessage={t(
              "No offload station yet. Create the RangerEdge as a device of this project, give it an Offload station entity with its place, and upload its card under Log files on its device page.",
            )}
          />
        </section>
        <section className="space-y-2">
          <h2 className="text-base font-semibold">{t("Trackers")}</h2>
          <DataTable
            columns={trackerColumns}
            data={data ? trackers : undefined}
            isLoading={overview.isPending}
            defaultHiddenSmall={["keys_set", "last_f_cnt"]}
            searchable
            cardOf={(tr) => (
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    className="font-medium underline"
                    to={devicePath(tr.device_id)}
                  >
                    {tr.device_name}
                  </Link>
                  {tr.entity_id && tr.entity_name && (
                    <Link
                      className="text-xs underline"
                      to={entityPath(tr.entity_id)}
                    >
                      {tr.entity_name}
                    </Link>
                  )}
                </div>
                <div className="text-xs">
                  {tr.dev_addr ? (
                    <span className="font-mono">{tr.dev_addr}</span>
                  ) : (
                    <span className="text-destructive">{t("no address")}</span>
                  )}
                  {" · "}
                  {tr.keys_set ? (
                    t("keys set {{ago}}", { ago: formatAgo(tr.set_at, now) })
                  ) : (
                    <span className="text-destructive">{t("no keys")}</span>
                  )}
                </div>
                <div className="text-xs">
                  {tr.receptions > 0
                    ? t("{{frames}} frames at {{stations}} stations", {
                        frames: tr.receptions,
                        stations: tr.stations,
                      }) +
                      `, ${formatAgo(tr.last_reception_at, now)}` +
                      (tr.last_station_name
                        ? ` ${t("at")} ${tr.last_station_name}`
                        : "")
                    : t("No offload in 30 days")}
                </div>
              </div>
            )}
            emptyMessage={t(
              "No tracker has an LP0 address yet. Set the address and the keys on each tracker's device page, under LP0 offload.",
            )}
            footer={
              data && data.devices_without_address > 0
                ? t(
                    "{{count}} devices of the project have no LP0 address yet",
                    {
                      count: data.devices_without_address,
                    },
                  )
                : undefined
            }
          />
        </section>
        {unknown.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-base font-semibold">
              {t("Addresses no device has")}
            </h2>
            <Callout kind="warning">
              {t(
                "The stations received frames of these addresses, and no device holds them. They wait: set the address and the keys on the tracker's device page, and the frames are decoded.",
              )}
              {serverAdmin && (
                <>
                  {" "}
                  <Link className="underline" to="/admin/attention">
                    {t("Needs attention lists them too.")}
                  </Link>
                </>
              )}
            </Callout>
            <DataTable
              columns={unknownColumns}
              data={unknown}
              defaultHiddenSmall={["first_seen_at"]}
            />
          </section>
        )}
      </Page>
    </>
  );
}
