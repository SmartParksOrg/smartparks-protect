import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device, DeviceType, Page as PageType } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { HealthLine } from "@/components/devices/HealthCard";
import { Icon } from "@/components/icons/Icon";
import { useNow } from "@/hooks/useNow";
import { useTechnicalDetails } from "@/hooks/useTechnicalDetails";
import { UNGROUPED, useGroups } from "@/hooks/useGroups";
import { formatAgo } from "@/lib/format";

export function DevicesPage() {
  const { t } = useTranslation();
  const now = useNow();
  const [technical] = useTechnicalDetails();
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, q, group }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: {
          project_id: projectId,
          q: q || undefined,
          group_id: group && group !== UNGROUPED ? group : undefined,
          limit: 500,
        },
      }),
    placeholderData: (previous) => previous,
    select: (page) =>
      group === UNGROUPED
        ? { ...page, items: page.items.filter((d) => !d.group_id) }
        : page,
  });
  const groups = useGroups(projectId);
  const groupName = (id: string | null | undefined) =>
    groups.data?.find((g) => g.id === id)?.name ?? "";
  const types = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", {
        query: { limit: 500 },
      }),
  });
  const typeById = new Map(types.data?.items.map((t) => [t.id, t]));
  const columns: ColumnDef<Device, unknown>[] = [
    {
      header: t("Name"),
      accessorKey: "name",
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-2">
          <Icon iconKey={typeById.get(row.original.device_type_id)?.icon_key} />
          {row.original.name}
        </span>
      ),
    },
    {
      header: t("Type"),
      accessorFn: (d) => typeById.get(d.device_type_id)?.label ?? "",
    },
    ...(technical
      ? [
          {
            header: t("Driver"),
            accessorFn: (d: Device) =>
              typeById.get(d.device_type_id)?.driver_key ?? "",
          } as ColumnDef<Device, unknown>,
        ]
      : []),
    {
      header: t("Status"),
      accessorKey: "status",
      cell: ({ getValue }) => <StatusBadge value={getValue<string>()} />,
    },
    { header: t("Serial"), accessorKey: "serial_number" },
    {
      header: t("Entity"),
      accessorKey: "entity_name",
      cell: ({ row }) =>
        row.original.entity_id ? (
          <Link
            className="underline"
            to={`/projects/${projectId}/entities/${row.original.entity_id}`}
            onClick={(ev) => ev.stopPropagation()}
          >
            {row.original.entity_name}
          </Link>
        ) : (
          <span className="text-muted-foreground">{t("none")}</span>
        ),
    },
    ...(groups.data && groups.data.length > 0
      ? [
          {
            header: t("Group"),
            accessorFn: (d: Device) => groupName(d.group_id),
          } as ColumnDef<Device, unknown>,
        ]
      : []),
    {
      header: t("Last seen"),
      accessorKey: "last_seen_at",
      cell: ({ getValue }) => formatAgo(getValue<string | null>(), now),
    },
    {
      header: t("Health"),
      id: "health",
      accessorFn: (d) => d.health?.level ?? "",
      cell: ({ row }) => <HealthLine health={row.original.health} />,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("Devices")}
        description={t("Hardware currently assigned to this project")}
        actions={
          <GroupSelect
            projectId={projectId}
            mode="filter"
            value={group}
            onChange={setGroup}
            className="h-9 w-44"
          />
        }
      />
      <Page>
        <DataTable
          columns={columns}
          data={devices.data?.items}
          searchable
          onSearchChange={setQ}
          footer={
            devices.data?.next_cursor
              ? t("Only the first 500 rows are shown. Search to find the rest.")
              : undefined
          }
          isLoading={devices.isPending}
          emptyMessage={t("No devices are assigned to this project.")}
          onRowClick={(d) => navigate(`/projects/${projectId}/devices/${d.id}`)}
        />
      </Page>
    </>
  );
}
