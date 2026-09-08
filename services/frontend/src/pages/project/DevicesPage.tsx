import { useTranslation } from "react-i18next";
import { MapPin } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProjects } from "@/hooks/useProjects";
import { isAllProjects, projectFor } from "@/lib/scope";
import { queryKeys } from "@/api/queryKeys";
import type { Device, DeviceType, Page as PageType } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { BulkAssignDialog } from "@/components/devices/BulkAssignDialog";
import { HealthLine } from "@/components/devices/HealthCard";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/icons/Icon";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import { useNow } from "@/hooks/useNow";
import { UNGROUPED, useGroups } from "@/hooks/useGroups";
import { formatAgo } from "@/lib/format";

export function DevicesPage() {
  const { t } = useTranslation();
  const now = useNow();
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [assigning, setAssigning] = useState<Device[]>([]);
  const allProjects = isAllProjects(projectId);
  const projectList = useProjects();
  const projectName = (id: string | null | undefined) =>
    projectList.data?.items.find((p) => p.id === id)?.name ?? "";
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, q, group, projectFilter }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: {
          project_id: allProjects
            ? projectFilter && projectFilter !== "none"
              ? projectFilter
              : undefined
            : projectId,
          in_no_project:
            allProjects && projectFilter === "none" ? true : undefined,
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
              <Icon
                iconKey={typeById.get(row.original.device_type_id)?.icon_key}
              />
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
    {
      id: "driver",
      header: t("Driver"),
      accessorFn: (d) => typeById.get(d.device_type_id)?.driver_key ?? "",
    },
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
      meta: { filter: false },
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
            ? t(
                "Every device on the server with the project it is assigned to today",
              )
            : t("Hardware currently assigned to this project")
        }
        actions={
          <>
            {allProjects && (
              <Select
                value={projectFilter || "all"}
                onValueChange={(v) => setProjectFilter(v === "all" ? "" : v)}
              >
                <SelectTrigger className="h-9 w-52" aria-label={t("Project")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("All projects")}</SelectItem>
                  <SelectItem value="none">{t("Not in a project")}</SelectItem>
                  {(projectList.data?.items ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
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
        {allProjects && selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
            <span>{t("{{count}} selected", { count: selected.size })}</span>
            <Button
              size="sm"
              onClick={() =>
                setAssigning(
                  (devices.data?.items ?? []).filter((d) => selected.has(d.id)),
                )
              }
            >
              {t("Assign to project")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelected(new Set())}
            >
              {t("Clear selection")}
            </Button>
          </div>
        )}
        <DataTable
          columns={columns}
          data={devices.data?.items}
          searchable
          columnFilters={allProjects}
          selection={
            allProjects
              ? { selected, onChange: setSelected, rowId: (d) => d.id }
              : undefined
          }
          onSearchChange={setQ}
          footer={
            devices.data?.next_cursor
              ? t("Only the first 500 rows are shown. Search to find the rest.")
              : undefined
          }
          isLoading={devices.isPending}
          emptyMessage={
            allProjects
              ? t("No device matches the filter.")
              : t(
                  "No devices are assigned to this project. A server admin assigns them under Server admin, Devices, or creates them from Needs attention.",
                )
          }
          columnsKey="devices"
          defaultHidden={["driver"]}
          defaultHiddenSmall={["type", "driver", "serial_number", "status"]}
          onRowClick={(d) =>
            navigate(
              `/projects/${projectFor(projectId, d.project_id)}/devices/${d.id}`,
            )
          }
        />
        {allProjects && (
          <BulkAssignDialog
            devices={assigning}
            onClose={() => setAssigning([])}
            onDone={() => setSelected(new Set())}
          />
        )}
      </Page>
    </>
  );
}
