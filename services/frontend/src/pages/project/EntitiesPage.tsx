import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { BellRing, Link2, MapPin, Plus, Wheat } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router";

import { api } from "@/api/client";
import { useProjects } from "@/hooks/useProjects";
import { isAllProjects, projectFor } from "@/lib/scope";
import { queryKeys } from "@/api/queryKeys";
import type { Entity, EntityType, Page as PageType } from "@/api/types";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { HealthLine } from "@/components/devices/HealthCard";
import { LoadMore } from "@/components/data/LoadMore";
import { AssignDeviceDialog } from "@/components/entities/AssignDeviceDialog";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { MoveToGroupDialog } from "@/components/entities/MoveToGroupDialog";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { useAnalysisModules, usePermissions } from "@/hooks/useProjects";
import { useNow } from "@/hooks/useNow";
import { usePages } from "@/hooks/usePages";
import { UNGROUPED, useGroups } from "@/hooks/useGroups";
import { formatAgo } from "@/lib/format";
import { positionKindExplanation, positionKindLabel } from "@/lib/positionKind";

// the order of the health levels, worst last, as the API judges them (decision D286)
const LEVEL_RANK: Record<string, number> = { ok: 0, warn: 1, critical: 2 };
const levelRank = (level: string | null | undefined) =>
  LEVEL_RANK[level ?? ""] ?? -1;

export function EntitiesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const { can } = usePermissions(projectId);
  const analysisModules = useAnalysisModules(projectId);
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Entity | null>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moving, setMoving] = useState<string[] | null>(null);
  const [assigning, setAssigning] = useState<Entity | null>(null);
  const entities = usePages<Entity>({
    queryKey: [...queryKeys.entities(projectId), q, group],
    fetchPage: (cursor) =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: {
          q: q || undefined,
          group_id: group && group !== UNGROUPED ? group : undefined,
          ungrouped: group === UNGROUPED ? true : undefined,
          limit: 500,
          cursor,
        },
      }),
    keepPrevious: true,
    // health and last seen are live, so an open list keeps up with its devices
    refetchInterval: 60_000,
  });
  const groups = useGroups(projectId);
  const groupName = (id: string | null | undefined) =>
    groups.data?.find((g) => g.id === id)?.name ?? "";
  const types = useQuery({
    queryKey: queryKeys.entityTypes,
    queryFn: () =>
      api.get<PageType<EntityType>>("/api/v1/entity-types", {
        query: { limit: 500 },
      }),
  });
  const typeById = useMemo(
    () => new Map(types.data?.items.map((t) => [t.id, t])),
    [types.data],
  );
  const now = useNow();
  const allProjects = isAllProjects(projectId);
  const projectList = useProjects();
  const projectName = (id: string | null | undefined) =>
    projectList.data?.items.find((p) => p.id === id)?.name ?? "";
  const columns: ColumnDef<Entity, unknown>[] = [
    ...(allProjects
      ? [
          {
            id: "project",
            header: t("Project"),
            accessorFn: (e: Entity) => projectName(e.project_id),
          } as ColumnDef<Entity, unknown>,
        ]
      : []),
    {
      header: t("Name"),
      accessorKey: "name",
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-2">
          <Icon
            iconKey={
              row.original.icon_key ??
              typeById.get(row.original.entity_type_id)?.icon_key
            }
          />
          {row.original.name}
        </span>
      ),
    },
    {
      header: t("Type"),
      accessorFn: (e) => typeById.get(e.entity_type_id)?.label ?? "",
    },
    ...(groups.data && groups.data.length > 0
      ? [
          {
            header: t("Group"),
            accessorFn: (e: Entity) => groupName(e.group_id),
          } as ColumnDef<Entity, unknown>,
        ]
      : []),
    {
      id: "health",
      header: t("Health"),
      accessorFn: (e) => e.tracking?.level ?? "",
      cell: ({ row }) => {
        const devices = row.original.tracking?.devices ?? [];
        // the device that drives the entity's level speaks for it (decision D286)
        const worst = [...devices].sort(
          (a, b) => levelRank(b.health?.level) - levelRank(a.health?.level),
        )[0];
        if (!worst?.health) return null;
        return (
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <HealthLine health={worst.health} />
            {devices.length > 1 && (
              <span className="text-xs text-muted-foreground">
                {worst.name}
              </span>
            )}
          </span>
        );
      },
    },
    {
      id: "devices",
      header: t("Devices"),
      accessorFn: (e) =>
        (e.tracking?.devices ?? []).map((d) => d.name).join(", "),
      cell: ({ row }) => {
        const devices = row.original.tracking?.devices ?? [];
        if (devices.length > 0)
          return (
            <span className="inline-flex flex-wrap gap-x-2">
              {devices.map((d) => (
                <Link
                  key={d.id}
                  className="underline"
                  to={`/projects/${projectFor(projectId, row.original.project_id)}/devices/${d.id}`}
                  onClick={(ev) => ev.stopPropagation()}
                >
                  {d.name}
                </Link>
              ))}
            </span>
          );
        return can("devices:write") && !allProjects ? (
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1 px-2 text-xs"
            onClick={(ev) => {
              ev.stopPropagation();
              setAssigning(row.original);
            }}
          >
            <Link2 className="size-3.5" /> {t("Assign device")}
          </Button>
        ) : (
          <span className="text-muted-foreground">{t("none")}</span>
        );
      },
    },
    {
      id: "last_seen",
      header: t("Last seen"),
      meta: { filter: false },
      accessorFn: (e) => e.tracking?.last_seen_at ?? undefined,
      cell: ({ getValue }) => formatAgo(getValue<string | undefined>(), now),
    },
    {
      // when data last arrived, apart from the records' own time: an animal without a
      // position whose readings come out of a flash log shows here that data came in
      // (Tim, 2026-09-24)
      id: "data_received",
      header: t("Data received"),
      meta: { filter: false },
      accessorFn: (e) => e.tracking?.data_received_at ?? undefined,
      cell: ({ getValue }) => formatAgo(getValue<string | undefined>(), now),
    },
    {
      id: "last_position",
      header: t("Last position"),
      meta: { filter: false },
      accessorFn: (e) => e.tracking?.position_time ?? undefined,
      cell: ({ row }) => {
        const tracking = row.original.tracking;
        if (!tracking?.position_time)
          return <span className="text-muted-foreground">{t("none")}</span>;
        const kind = positionKindLabel(tracking.position_kind, t);
        return (
          <span>
            {formatAgo(tracking.position_time, now)}
            {kind && (
              <span
                className="ml-1 text-xs text-muted-foreground"
                title={positionKindExplanation(tracking.position_kind, t)}
              >
                {kind}
              </span>
            )}
          </span>
        );
      },
    },
    {
      id: "alerts",
      header: t("Open alerts"),
      meta: { filter: false },
      accessorFn: (e) => e.tracking?.active_alert_count ?? 0,
      cell: ({ getValue, row }) => {
        const count = getValue<number>();
        return count > 0 ? (
          <Link
            className="inline-flex items-center gap-1 text-destructive underline"
            to={`/projects/${projectFor(projectId, row.original.project_id)}/alerts`}
            onClick={(ev) => ev.stopPropagation()}
          >
            <BellRing className="size-3.5" /> {count}
          </Link>
        ) : (
          <span className="text-muted-foreground">0</span>
        );
      },
    },
    {
      id: "status",
      header: t("Status"),
      accessorKey: "status",
      cell: ({ getValue }) => <StatusBadge value={getValue<string>()} />,
    },
    {
      id: "map",
      header: "",
      cell: ({ row }) =>
        row.original.tracking?.position_time ? (
          <Link
            className="inline-flex items-center gap-1 text-xs underline"
            to={`/projects/${projectFor(projectId, row.original.project_id)}/map?entity=${row.original.id}`}
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
        title={t("Entities")}
        description={t(
          "Animals, people, vehicles, gates and other monitored objects",
        )}
        actions={
          <>
            <GroupSelect
              projectId={projectId}
              mode="filter"
              value={group}
              onChange={setGroup}
              className="h-9 w-44"
            />
            {group &&
              group !== UNGROUPED &&
              analysisModules.includes("grazing") &&
              can("analysis:run") && (
                <Button asChild variant="outline">
                  <Link
                    to={`/projects/${projectId}/analyze/grazing?group=${group}`}
                  >
                    <Wheat className="size-4" /> {t("Analyse grazing")}
                  </Link>
                </Button>
              )}
            {can("entities:write") && (
              <Button
                onClick={() => {
                  setEditing(null);
                  setOpen(true);
                }}
              >
                <Plus className="size-4" /> {t("New entity")}
              </Button>
            )}
          </>
        }
      />
      <Page>
        {can("entities:write") && selected.size > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
            <span>{t("{{count}} selected", { count: selected.size })}</span>
            <Button size="sm" onClick={() => setMoving([...selected])}>
              {t("Move to group…")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelected(new Set())}
            >
              {t("Clear")}
            </Button>
          </div>
        )}
        <DataTable
          columns={columns}
          data={entities.items}
          searchable
          onSearchChange={setQ}
          footer={
            <LoadMore
              count={entities.items.length}
              hasMore={entities.hasMore}
              isLoading={entities.isLoadingMore}
              onLoadMore={entities.loadMore}
            />
          }
          isLoading={entities.isPending}
          emptyMessage={t(
            "No entities yet. Add one with New entity, or onboard devices with their animals from Needs attention.",
          )}
          columnsKey="entities"
          defaultHidden={["status"]}
          defaultHiddenSmall={["type", "last_position", "alerts"]}
          onRowClick={(e) =>
            void navigate(
              `/projects/${projectFor(projectId, e.project_id)}/entities/${e.id}`,
            )
          }
          selection={
            can("entities:write")
              ? { selected, onChange: setSelected, rowId: (e) => e.id }
              : undefined
          }
        />
      </Page>
      <EntityDialog
        projectId={projectId}
        entity={editing}
        open={open}
        onOpenChange={setOpen}
      />
      {assigning && (
        <AssignDeviceDialog
          projectId={projectId}
          entityId={assigning.id}
          entityName={assigning.name}
          open
          onOpenChange={(o) => !o && setAssigning(null)}
        />
      )}
      <MoveToGroupDialog
        projectId={projectId}
        entityIds={moving ?? []}
        open={moving != null}
        onOpenChange={(o) => !o && setMoving(null)}
        onMoved={() => setSelected(new Set())}
      />
    </>
  );
}
