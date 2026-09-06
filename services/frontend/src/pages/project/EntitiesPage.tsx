import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, MapPin } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CurrentState, Entity, EntityType, Page as PageType, Device } from "@/api/types";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useNow } from "@/hooks/useNow";
import { formatAgo } from "@/lib/format";

export function EntitiesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Entity | null>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const entities = useQuery({ queryKey: [...queryKeys.entities(projectId), q], queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { q: q || undefined, limit: 500 } }), placeholderData: (previous) => previous });
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const state = useQuery({ queryKey: queryKeys.currentState(projectId), queryFn: () => api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`) });
  const typeById = useMemo(() => new Map(types.data?.items.map((t) => [t.id, t])), [types.data]);
  const now = useNow();
  const projectDevices = useQuery({ queryKey: queryKeys.devices({ projectId }), queryFn: () => api.get<PageType<Device>>("/api/v1/devices", { query: { project_id: projectId, limit: 500 } }), enabled: Boolean(projectId) });
  const deviceNames = useMemo(() => new Map((projectDevices.data?.items ?? []).map((d) => [d.id, d.name])), [projectDevices.data]);
  const lastSeen = useMemo(() => new Map((state.data?.features as unknown as { properties: EntityFeatureProperties }[] | undefined)?.map((f) => [f.properties.entity_id, f.properties])), [state.data]);

  const columns: ColumnDef<Entity, unknown>[] = [
    { header: t("Name"), accessorKey: "name", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key ?? typeById.get(row.original.entity_type_id)?.icon_key} />{row.original.name}</span> },
    { header: t("Type"), accessorFn: (e) => typeById.get(e.entity_type_id)?.label ?? "" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Last seen"), accessorFn: (e) => lastSeen.get(e.id)?.last_seen_at ?? undefined, cell: ({ getValue }) => formatAgo(getValue<string | undefined>(), now) },
    { header: t("Device"), accessorFn: (e) => deviceNames.get(lastSeen.get(e.id)?.device_id ?? "") ?? "", cell: ({ row }) => { const id = lastSeen.get(row.original.id)?.device_id; return id ? <Link className="underline" to={`/projects/${projectId}/devices/${id}`} onClick={(ev) => ev.stopPropagation()}>{deviceNames.get(id) ?? t("open device")}</Link> : <span className="text-muted-foreground">{t("none")}</span>; } },
    { id: "map", header: "", cell: ({ row }) => (lastSeen.get(row.original.id)?.position_time ? <Link className="inline-flex items-center gap-1 text-xs underline" to={`/projects/${projectId}/map?entity=${row.original.id}`} onClick={(ev) => ev.stopPropagation()}><MapPin className="size-3" /> {t("Map")}</Link> : null) },
  ];

  return (
    <>
      <PageHeader title={t("Entities")} description={t("Animals, people, vehicles, gates and other monitored objects")} actions={canAdmin(role) && <Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New entity")}</Button>} />
      <Page>
        <DataTable columns={columns} data={entities.data?.items} searchable onSearchChange={setQ} footer={entities.data?.next_cursor ? t("Only the first 500 rows are shown. Search to find the rest.") : undefined} isLoading={entities.isPending} emptyMessage={t("No entities yet.")} onRowClick={(e) => void navigate(`/projects/${projectId}/entities/${e.id}`)} />
      </Page>
      <EntityDialog projectId={projectId} entity={editing} open={open} onOpenChange={setOpen} />
    </>
  );
}
