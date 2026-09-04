import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Connection } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

/** The AI clients the signed-in user has connected through OAuth, with a way to disconnect. */
export function ConnectionsPage() {
  const connections = useQuery({ queryKey: queryKeys.connections, queryFn: () => api.get<Connection[]>("/api/v1/oauth/connections", { query: { limit: 100 } }) });
  const [revoking, setRevoking] = useState<Connection | null>(null);
  const revoke = useMutationToast({
    mutationFn: (clientId: string) => api.post("/api/v1/oauth/connections/revoke", { body: { client_id: clientId } }),
    invalidate: [queryKeys.connections],
    success: "Client disconnected",
    onSuccess: () => setRevoking(null),
  });
  const label = (c: Connection) => (c.registration === "metadata_document" ? c.client_host ?? c.client_id : c.client_name ?? c.client_id);
  const columns: ColumnDef<Connection, unknown>[] = [
    { header: "Client", accessorFn: label, id: "client", cell: ({ row }) => (
      <div>
        <div className="font-medium">{label(row.original)}</div>
        {row.original.registration === "metadata_document" && row.original.client_name && <div className="text-xs text-muted-foreground">calls itself “{row.original.client_name}”</div>}
      </div>
    ) },
    { header: "Access", id: "scopes", cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.scopes.filter((s) => s !== "offline_access").join(", ")}</span> },
    { header: "Connected", accessorKey: "first_authorized_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: "Last used", accessorKey: "last_used_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) || "not yet" },
    { id: "actions", header: "", cell: ({ row }) => <Button variant="ghost" size="sm" onClick={() => setRevoking(row.original)}>Disconnect</Button> },
  ];
  return (
    <>
      <PageHeader title="Connected AI clients" description="Assistants that may read your data through the MCP server. They act as you, read only, and every request is in the audit log." />
      <Page>
        <DataTable columns={columns} data={connections.data} isLoading={connections.isPending} emptyMessage="No AI client is connected." />
      </Page>
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title="Disconnect this client?"
        description="It loses access at once for new sessions and within an hour for the current one. You can connect it again from the client."
        confirmLabel="Disconnect"
        pending={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking.client_id)}
      />
    </>
  );
}
