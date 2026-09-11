import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Link2, Plus, MapPin } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router";

import { api } from "@/api/client";
import { useProjects } from "@/hooks/useProjects";
import { isAllProjects, projectFor } from "@/lib/scope";
import { queryKeys } from "@/api/queryKeys";
import type {
  EntityAssignment,
  CurrentState,
  Entity,
  EntityType,
  Page as PageType,
  Device,
} from "@/api/types";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { LoadMore } from "@/components/data/LoadMore";
import { AssignDeviceDialog } from "@/components/entities/AssignDeviceDialog";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { MoveToGroupDialog } from "@/components/entities/MoveToGroupDialog";
import { Icon } from "@/components/icons/Icon";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import { Button } from "@/components/ui/button";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useNow } from "@/hooks/useNow";
import { usePages } from "@/hooks/usePages";
import { UNGROUPED, useGroups } from "@/hooks/useGroups";
import { formatAgo } from "@/lib/format";

export function EntitiesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
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
  const state = useQuery({
    queryKey: queryKeys.currentState(projectId),
    queryFn: () =>
      api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`),
  });
  const typeById = useMemo(
    () => new Map(types.data?.items.map((t) => [t.id, t])),
    [types.data],
  );
  const now = useNow();
  const projectDevices = useQuery({
    queryKey: queryKeys.devices({ projectId }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: allProjects ? undefined : projectId, limit: 500 },
      }),
    enabled: Boolean(projectId),
  });
  const deviceNames = useMemo(
    () =>
      new Map((projectDevices.data?.items ?? []).map((d) => [d.id, d.name])),
    [projectDevices.data],
  );
  const assignments = useQuery({
    queryKey: queryKeys.entityAssignments(projectId),
    queryFn: () =>
      api.get<PageType<EntityAssignment>>(
        `/api/v1/projects/${projectId}/entity-assignments`,
        { query: { limit: 500 } },
      ),
    enabled: Boolean(projectId) && !isAllProjects(projectId),
  });
  const tracked = useMemo(
    () =>
      new Set(
        (assignments.data?.items ?? [])
          .filter((a) => !a.valid_to)
          .map((a) => a.entity_id),
      ),
    [assignments.data],
  );
  const lastSeen = useMemo(
    () =>
      new Map(
        (
          state.data?.features as unknown as
            { properties: EntityFeatureProperties }[] | undefined
        )?.map((f) => [f.properties.entity_id, f.properties]),
      ),
    [state.data],
  );

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
          <ObjectPicture
            path={`/api/v1/projects/${projectId}/entities/${row.original.id}/picture`}
            updatedAt={row.original.picture_updated_at}
            name={row.original.name}
            size="xs"
            fallback={
              <Icon
                iconKey={
                  row.original.icon_key ??
                  typeById.get(row.original.entity_type_id)?.icon_key
                }
              />
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
    {
      header: t("Status"),
      accessorKey: "status",
      cell: ({ getValue }) => <StatusBadge value={getValue<string>()} />,
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
      header: t("Last seen"),
      accessorFn: (e) => lastSeen.get(e.id)?.last_seen_at ?? undefined,
      cell: ({ getValue }) => formatAgo(getValue<string | undefined>(), now),
    },
    {
      header: t("Device"),
      accessorFn: (e) =>
        deviceNames.get(lastSeen.get(e.id)?.device_id ?? "") ?? "",
      cell: ({ row }) => {
        const id = lastSeen.get(row.original.id)?.device_id;
        return id ? (
          <Link
            className="underline"
            to={`/projects/${projectFor(projectId, row.original.project_id)}/devices/${id}`}
            onClick={(ev) => ev.stopPropagation()}
          >
            {deviceNames.get(id) ?? t("open device")}
          </Link>
        ) : canAdmin(role) && !allProjects && assignments.data && !tracked.has(row.original.id) ? (
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
      id: "map",
      header: "",
      cell: ({ row }) =>
        lastSeen.get(row.original.id)?.position_time ? (
          <Link
            className="inline-flex items-center gap-1 text-xs underline"
            to={`/projects/${projectId}/map?entity=${row.original.id}`}
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
            {canAdmin(role) && (
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
        {canAdmin(role) && selected.size > 0 && (
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
            "No entities yet. Add one with New entity, or onboard collars with their animals from Needs attention.",
          )}
          columnsKey="entities"
          onRowClick={(e) =>
            void navigate(
              `/projects/${projectFor(projectId, e.project_id)}/entities/${e.id}`,
            )
          }
          selection={
            canAdmin(role)
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
