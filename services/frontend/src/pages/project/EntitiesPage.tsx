import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CurrentState, Entity, EntityType, Page as PageType } from "@/api/types";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { EntityDialog } from "@/components/entities/EntityDialog";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { formatAgo } from "@/lib/format";

export function EntitiesPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const role = useProjectRole(projectId);
  const navigate = useNavigate();
  const [editing, setEditing] = useState<Entity | null>(null);
  const [open, setOpen] = useState(false);
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }) });
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<PageType<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const state = useQuery({ queryKey: queryKeys.currentState(projectId), queryFn: () => api.get<CurrentState>(`/api/v1/projects/${projectId}/map/current`) });
  const typeById = useMemo(() => new Map(types.data?.items.map((t) => [t.id, t])), [types.data]);
  const lastSeen = useMemo(() => new Map((state.data?.features as unknown as { properties: EntityFeatureProperties }[] | undefined)?.map((f) => [f.properties.entity_id, f.properties])), [state.data]);

  const columns: ColumnDef<Entity, unknown>[] = [
    { header: t("Name"), accessorKey: "name", cell: ({ row }) => <span className="inline-flex items-center gap-2"><Icon iconKey={row.original.icon_key ?? typeById.get(row.original.entity_type_id)?.icon_key} />{row.original.name}</span> },
    { header: t("Type"), accessorFn: (e) => typeById.get(e.entity_type_id)?.label ?? "" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("Last seen"), accessorFn: (e) => lastSeen.get(e.id)?.last_seen_at ?? undefined, cell: ({ getValue }) => formatAgo(getValue<string | undefined>()) },
    { header: t("Device"), accessorFn: (e) => lastSeen.get(e.id)?.device_id ?? undefined, cell: ({ getValue }) => (getValue<string | undefined>() ? "assigned" : "none") },
  ];

  return (
    <>
      <PageHeader title={t("Entities")} description={t("Animals, people, vehicles, gates and other monitored objects")} actions={canAdmin(role) && <Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New entity")}</Button>} />
      <Page>
        <DataTable columns={columns} data={entities.data?.items} isLoading={entities.isPending} emptyMessage={t("No entities yet.")} onRowClick={(e) => {
            if (canAdmin(role)) {
              setEditing(e);
              setOpen(true);
            } else void navigate(`/projects/${projectId}/map?entity=${e.id}`);
          }} />
      </Page>
      <EntityDialog projectId={projectId} entity={editing} open={open} onOpenChange={setOpen} />
    </>
  );
}
