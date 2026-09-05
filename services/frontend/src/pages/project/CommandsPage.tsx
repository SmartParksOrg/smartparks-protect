import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { CommandItem, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { CommandDetailDialog } from "@/components/control/DeviceControl";
import { DataTable } from "@/components/data/DataTable";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProjectStream } from "@/hooks/useProjectStream";
import { formatTime } from "@/lib/format";

const STATUSES = ["queued", "transmitted", "acknowledged", "confirmed_by_device", "failed", "expired"];

/** Every command of the project, newest first (architecture 17): who asked, what was sent, how far it got. */
export function CommandsPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const selected = params.get("command");
  const query = { status: status || undefined, limit: 200 };
  const commands = useQuery({ queryKey: queryKeys.projectCommands(projectId, query), queryFn: () => api.get<PageType<CommandItem>>(`/api/v1/projects/${projectId}/commands`, { query }), refetchInterval: 30_000 });
  const client = useQueryClient();
  useProjectStream(projectId, (m) => { if (m.topic === "command.updated") void client.invalidateQueries({ queryKey: ["projects", projectId, "commands"] }); });

  const columns: ColumnDef<CommandItem, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => <span className="whitespace-nowrap">{formatTime(getValue<string>())}</span> },
    { header: t("Action"), accessorKey: "action_key" },
    { header: t("Device"), accessorKey: "external_id", cell: ({ row }) => <span className="font-mono text-xs">{row.original.external_id ?? row.original.device_id.slice(0, 8)}</span> },
    { header: t("Route"), accessorKey: "route" },
    { header: t("Status"), accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={getValue<string>()} /> },
    { header: t("By"), accessorFn: (c) => String(c.actor.kind ?? "") },
    { header: t("Detail"), accessorKey: "error_message", cell: ({ getValue }) => <span className="text-xs text-destructive">{getValue<string | null>() ?? ""}</span> },
  ];

  return (
    <>
      <PageHeader title={t("Commands")} description={t("Every command sent to a device of this project, by people and by automations, with its lifecycle")} />
      <Page>
        <Select value={status || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("status"); else p.set("status", v); return p; }, { replace: true })}>
          <SelectTrigger className="w-48" aria-label={t("Status")}><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">{t("Any status")}</SelectItem>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s.replaceAll("_", " ")}</SelectItem>)}</SelectContent>
        </Select>
        {commands.error && <Callout kind="error">{commands.error.message}</Callout>}
        <DataTable columns={columns} data={commands.data?.items} searchable isLoading={commands.isPending} emptyMessage={t("No commands yet. Open a device and use its Actions menu.")} onRowClick={(c) => setParams((p) => { p.set("command", c.id); return p; }, { replace: true })} footer={commands.data && `${commands.data.items.length} commands`} />
      </Page>
      <CommandDetailDialog commandId={selected} projectId={projectId} onClose={() => setParams((p) => { p.delete("command"); return p; }, { replace: true })} />
    </>
  );
}
