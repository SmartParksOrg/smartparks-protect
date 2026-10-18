import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useParams } from "react-router";
import {
  BookOpen,
  CircleCheck,
  CircleHelp,
  HardDrive,
  Laptop,
  List,
  Map as MapIcon,
  Plus,
  Radio,
} from "lucide-react";

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
import { CardUploadButton } from "@/components/network/CardUploadButton";
import { FieldCard } from "@/components/network/FieldCard";
import { FilesSection } from "@/components/network/FilesSection";
import { OffloadStationDialog } from "@/components/network/OffloadStationDialog";
import { StationsMap } from "@/components/network/StationsMap";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useNow } from "@/hooks/useNow";
import { usePermissions } from "@/hooks/useProjects";
import { useStationsView } from "@/hooks/useStationsView";
import { formatAgo, formatTime } from "@/lib/format";

/**
 * The project's LP0 network on one page (phase 42, Tim, 2026-10-16): every offload station
 * with what its cards brought and its own last report, every tracker with an LP0 address or
 * frames (the keys stay on the device page, behind Show), and the addresses the stations
 * received that no device has. The page lists and links; a tracker's address and keys and a
 * station's card are set on the device pages, so each row is a link away. The one thing the
 * page does itself is the station's setup (Tim, 2026-10-16, the same day): "Make an offload
 * station" turns a device of the project into one in one dialog, the Setup column says what a
 * row still misses and opens that dialog for it, and the guide under "How to set up" is the
 * three steps in one place, hidden until the button is pressed (Tim, 2026-10-16). A RangerEdge
 * that is not a device yet is added inside that dialog, by hand or read over Bluetooth with its
 * LP0 credentials (decision D326). "Protect Go" (decision D332, Tim,
 * 2026-10-17) opens the card that installs Protect Go, the app for the place without a connection.
 * Figures cover the last 30 days, as on the Gateways page.
 */
export function OffloadPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const now = useNow();
  const { can, all: serverAdmin } = usePermissions(projectId);
  const canSetUp = can("devices:write");
  const canUpload = can("devices:control");
  const [setup, setSetup] = useState<{
    open: boolean;
    deviceId: string | null;
  }>({
    open: false,
    deviceId: null,
  });
  const [guideOpen, setGuideOpen] = useState(false);
  const [stationsView, setStationsView] = useStationsView();
  const [fieldOpen, setFieldOpen] = useState(false);
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

  // What a station still misses before a card can be read into it, in the order of the
  // guide; a piece the dialog sets opens the dialog, the card is uploaded on the device page.
  type Gap = { label: string; hint: string; fix: "dialog" | "device" | "none" };
  const stationGaps = (s: OffloadOverviewStation): Gap[] => {
    const gaps: Gap[] = [];
    if (!s.entity_id)
      gaps.push({
        label: t("no entity"),
        hint: t(
          "The station has no Offload station entity, so it is not on the map or in the lists",
        ),
        fix: "dialog",
      });
    if (!s.has_location)
      gaps.push({
        label: t("no place"),
        hint: t("A station does not move: set its place by hand"),
        fix: "dialog",
      });
    if (!s.gateway_id)
      gaps.push({
        label: t("not a gateway yet"),
        hint: t(
          "The station has no row among the gateways of the offload station source until it is set up or its first card is read",
        ),
        fix: "dialog",
      });
    if (s.files === 0)
      gaps.push({
        label: t("no card yet"),
        hint: t(
          "Upload the card's files under Log files on the station's device page",
        ),
        fix: "device",
      });
    if (s.card_ok === false)
      gaps.push({
        label: t("card not writable"),
        hint: t(
          "The station's own report says its SD card is out or cannot be written",
        ),
        fix: "none",
      });
    return gaps;
  };
  const trackerGaps = (tr: OffloadOverviewTracker): Gap[] => {
    if (!tr.dev_addr)
      return [
        {
          label: t("address and keys not set"),
          hint: t(
            "Set the LP0 address and the two keys under LP0 offload on the device page",
          ),
          fix: "device",
        },
      ];
    if (tr.reported_dev_addr && tr.reported_dev_addr !== tr.dev_addr)
      return [
        {
          label: t("address differs from the device's"),
          hint: t(
            "The device reports another address in its settings; check which one is provisioned",
          ),
          fix: "device",
        },
      ];
    return [];
  };
  const gapBadges = (gaps: Gap[], deviceId: string) =>
    gaps.length === 0 ? (
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <CircleCheck className="size-3.5" /> {t("complete")}
      </span>
    ) : (
      <span className="flex flex-wrap gap-1">
        {gaps.map((gap) =>
          gap.fix === "dialog" && canSetUp ? (
            <button
              key={gap.label}
              type="button"
              className="inline-flex"
              title={gap.hint}
              onClick={() => setSetup({ open: true, deviceId })}
            >
              <Badge
                variant="outline"
                className="cursor-pointer text-destructive"
              >
                {gap.label}
              </Badge>
            </button>
          ) : gap.fix === "none" ? (
            <Badge
              key={gap.label}
              variant="outline"
              className="text-destructive"
              title={gap.hint}
            >
              {gap.label}
            </Badge>
          ) : (
            <Link key={gap.label} to={devicePath(deviceId)} title={gap.hint}>
              <Badge variant="outline" className="text-destructive">
                {gap.label}
              </Badge>
            </Link>
          ),
        )}
      </span>
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
      header: t("Setup"),
      id: "setup",
      cell: ({ row }) =>
        gapBadges(stationGaps(row.original), row.original.device_id),
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
    {
      header: t("Setup"),
      id: "setup",
      cell: ({ row }) =>
        gapBadges(trackerGaps(row.original), row.original.device_id),
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
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-pressed={guideOpen}
              onClick={() => setGuideOpen((v) => !v)}
            >
              <BookOpen className="size-4" /> {t("How to set up")}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-pressed={fieldOpen}
              onClick={() => setFieldOpen((v) => !v)}
            >
              <Laptop className="size-4" /> {t("Protect Go")}
            </Button>
            {canSetUp && (
              <Button
                type="button"
                size="sm"
                variant={canUpload ? "outline" : "default"}
                onClick={() => setSetup({ open: true, deviceId: null })}
              >
                <Plus className="size-4" /> {t("Make an offload station")}
              </Button>
            )}
            {canUpload && <CardUploadButton projectId={projectId} />}
          </>
        }
      />
      <Page>
        {overview.error && (
          <Callout kind="error">{overview.error.message}</Callout>
        )}
        {fieldOpen && <FieldCard />}
        {guideOpen && (
          <Callout kind="info">
            <p className="font-medium">{t("How to set up offload stations")}</p>
            <ol className="mt-1 list-decimal space-y-1 pl-4">
              <li>
                {t(
                  'The station: a RangerEdge with an SD card. "Make an offload station" picks it among the project\'s devices, or adds it first, by hand or read over Bluetooth, with its DevEUI as serial number; then it gets an Offload station entity, its place and its row among the gateways. A station does not move, so its place is set by hand.',
                )}
              </li>
              <li>
                {t(
                  "The trackers: on each tracker's device page, under LP0 offload, set the LP0 address and the two session keys provisioned on the device, or take them from the device's own readback; a tracker added over Bluetooth in the station dialog brings them with it. The address is how a frame on a card finds its device; the keys decrypt it.",
                )}
              </li>
              <li>
                {t(
                  "The card: \"Upload SD card files\" here takes the .jsonl files or zips of the LOG folders of any number of cards and puts each file with the station named in it; a station's device page takes its own files too, under Log files. Every frame is verified and decrypted with its tracker's own keys and the records appear on the trackers' entities. The Setup column here says what a row still misses.",
                )}
              </li>
            </ol>
          </Callout>
        )}
        {canSetUp && (
          <OffloadStationDialog
            projectId={projectId}
            open={setup.open}
            deviceId={setup.deviceId}
            onOpenChange={(open) => setSetup((s) => ({ ...s, open }))}
          />
        )}
        <section className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <HardDrive className="size-4" /> {t("Stations")}
            </h2>
            {/* a list or a map of the stations (Tim, 2026-10-18), remembered per person */}
            <div
              className="flex rounded-md border p-0.5"
              role="group"
              aria-label={t("View")}
            >
              <Button
                type="button"
                variant={stationsView === "list" ? "secondary" : "ghost"}
                size="icon"
                className="size-7"
                aria-pressed={stationsView === "list"}
                aria-label={t("List")}
                onClick={() => setStationsView("list")}
              >
                <List className="size-4" />
              </Button>
              <Button
                type="button"
                variant={stationsView === "map" ? "secondary" : "ghost"}
                size="icon"
                className="size-7"
                aria-pressed={stationsView === "map"}
                aria-label={t("Map")}
                onClick={() => setStationsView("map")}
              >
                <MapIcon className="size-4" />
              </Button>
            </div>
          </div>
          {stationsView === "map" && data ? (
            <StationsMap stations={stations} projectId={projectId} />
          ) : (
            <DataTable
              columns={stationColumns}
              data={data ? stations : undefined}
              isLoading={overview.isPending}
              defaultHiddenSmall={["last_upload_at", "report"]}
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
                  </div>
                  <div className="text-xs">
                    {gapBadges(stationGaps(s), s.device_id)}
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
              emptyMessage={
                canSetUp
                  ? t(
                      'No offload station yet. "Make an offload station" picks the RangerEdge among the project\'s devices or adds it first; the guide says what comes next.',
                    )
                  : t(
                      'No offload station yet. A project admin makes one from a RangerEdge of this project with "Make an offload station".',
                    )
              }
            />
          )}
        </section>
        <section className="space-y-2">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Radio className="size-4" /> {t("Trackers")}
          </h2>
          <DataTable
            columns={trackerColumns}
            data={data ? trackers : undefined}
            isLoading={overview.isPending}
            defaultHiddenSmall={["keys_set", "last_f_cnt", "setup"]}
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
                {trackerGaps(tr).length > 0 && (
                  <div className="text-xs">
                    {gapBadges(trackerGaps(tr), tr.device_id)}
                  </div>
                )}
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
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <CircleHelp className="size-4" /> {t("Addresses no device has")}
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
        <FilesSection projectId={projectId} canWrite={canUpload} />
      </Page>
    </>
  );
}
