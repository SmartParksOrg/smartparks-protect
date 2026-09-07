import { useTranslation } from "react-i18next";
import { MapPin } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProjects } from "@/hooks/useProjects";
import { isAllProjects, projectFor } from "@/lib/scope";
import { queryKeys } from "@/api/queryKeys";
import type { Device, DeviceType, Page as PageType } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { HealthLine } from "@/components/devices/HealthCard";
import { Icon } from "@/components/icons/Icon";
import { ObjectPicture } from "@/components/common/ObjectPicture";
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
  const [projectFilter, setProjectFilter] = useState("");
  const allProjects = isAllProjects(projectId);
  const projectList = useProjects();
  const projectName = (id: string | null | undefined) =>
    projectList.data?.items.find((p) => p.id === id)?.name ?? "";
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, q, group }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: {
          project_id: allProjects ? undefined : projectId,
          q: q || undefined,
          group_id: group && group !== UNGROUPED ? group : undefined,
          limit: 500,
        },
      }),
    placeholderData: (previous) => previous,
    select: (page) => {
      let items = page.items;
      if (group === UNGROUPED) items = items.filter((d) => !d.group_id);
      if (projectFilter === "none") items = items.filter((d) => !d.project_id);
      else if (projectFilter) items = items.filter((d) => d.project_id === projectFilter);
      return { ...page, items };
    },
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
    ...(allProjects
      ? [
          {
            id: "project",
            header: t("Project"),
            accessorFn: (d: Device) => projectName(d.project_id) || t("none"),
          } as ColumnDef<Device, unknown>,
        ]
      : []),
    {
      header: t("Name"),
      accessorKey: "name",
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-2">
          <ObjectPicture
            path={`/api/v1/devices/${row.original.id}/picture`}
            updatedAt={row.original.picture_updated_at}
            name={row.original.name}
            size="xs"
            fallback={
              <Icon iconKey={typeById.get(row.original.device_type_id)?.icon_key} />
            }
          />
          {row.original.name}
        </span>
      ),
    },
    {
      id: "type",
      header: t("Type"),
      accessorFn: (d) => typeById.get(d.device_type_id)?.label ?? "",
    },
    ...(technical
      ? [
          {
            id: "driver",
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
    {
      id: "map",
      header: "",
      cell: ({ row }) =>
        row.original.last_seen_at ? (
          <Link
            className="inline-flex items-center gap-1 text-xs underline"
            to={`/projects/${projectId}/map?device=${row.original.id}`}
            onClick={(ev) => ev.stopPropagation()}
          >
            <MapPin className="size-3" /> {t("Map")}
          </Link>
        ) : null,
    },
  ];
  return (
    <>
      <PageHeader
        title={t("Devices")}
        description={
          allProjects
            ? t("Every device on the server with the project it is assigned to today")
            : t("Hardware currently assigned to this project")
        }
        actions={
          <>
            {allProjects && (
              <Select value={projectFilter || "all"} onValueChange={(v) => setProjectFilter(v === "all" ? "" : v)}>
                <SelectTrigger className="h-9 w-52" aria-label={t("Project")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("All projects")}</SelectItem>
                  <SelectItem value="none">{t("Not in a project")}</SelectItem>
                  {(projectList.data?.items ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <GroupSelect
              projectId={projectId}
              mode="filter"
              value={group}
              onChange={setGroup}
              className="h-9 w-44"
            />
          </>
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
          emptyMessage={t("No devices are assigned to this project. A server admin assigns them under Server admin, Devices, or creates them from Needs attention.")} columnsKey="devices"
          defaultHiddenSmall={["type", "driver", "serial_number", "status"]}
          onRowClick={(d) =>
            navigate(`/projects/${projectFor(projectId, d.project_id)}/devices/${d.id}`)
          }
        />
      </Page>
    </>
  );
}
