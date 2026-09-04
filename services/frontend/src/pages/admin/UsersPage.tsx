import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Invitation, Page as PageType, UserAdmin } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatAgo, formatTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

export function UsersPage() {
  const { t } = useTranslation();
  const me = useAuthStore((s) => s.user);
  const users = useQuery({ queryKey: queryKeys.users, queryFn: () => api.get<PageType<UserAdmin>>("/api/v1/admin/users", { query: { limit: 500 } }) });
  const invitations = useQuery({ queryKey: queryKeys.serverInvitations, queryFn: () => api.get<PageType<Invitation>>("/api/v1/admin/invitations", { query: { limit: 500 } }) });
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const update = useMutationToast({ mutationFn: ({ id, body }: { id: string; body: Record<string, boolean> }) => api.patch(`/api/v1/admin/users/${id}`, { body }), invalidate: [queryKeys.users], success: t("User updated") });
  const invite = useMutationToast({
    mutationFn: () => api.post<Invitation & { mail_sent: boolean }>("/api/v1/admin/invitations", { body: { email } }),
    invalidate: [queryKeys.serverInvitations],
    success: (d) => (d.mail_sent ? "Invitation sent" : "Invitation created"),
    onSuccess: (d) => { setEmail(""); setNote(d.mail_sent ? null : "Mail is not configured; the registration link is in the API log."); },
  });
  const revoke = useMutationToast({ mutationFn: (id: string) => api.delete(`/api/v1/admin/invitations/${id}`), invalidate: [queryKeys.serverInvitations], success: t("Invitation revoked") });
  const userColumns: ColumnDef<UserAdmin, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Name"), accessorKey: "full_name" },
    { header: t("Active"), accessorKey: "is_active", cell: ({ row }) => <Switch checked={row.original.is_active} disabled={row.original.id === me?.id} onCheckedChange={(v) => update.mutate({ id: row.original.id, body: { is_active: v } })} aria-label={t("Active")} /> },
    { header: t("Server admin"), accessorKey: "is_superuser", cell: ({ row }) => <Switch checked={row.original.is_superuser} disabled={row.original.id === me?.id} onCheckedChange={(v) => update.mutate({ id: row.original.id, body: { is_superuser: v } })} aria-label={t("Server admin")} /> },
    { header: t("Last login"), accessorKey: "last_login_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
  ];
  const invitationColumns: ColumnDef<Invitation, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Kind"), accessorFn: (i) => (i.server_admin ? "server admin" : i.role ?? "") },
    { header: t("Expires"), accessorKey: "expires_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Used"), accessorKey: "used_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) || "not yet" },
    { id: "actions", header: "", cell: ({ row }) => (row.original.used_at ? null : <Button variant="ghost" size="sm" onClick={() => revoke.mutate(row.original.id)}>{t("Revoke")}</Button>) },
  ];
  return (
    <>
      <PageHeader title={t("Users")} description={t("Every account on this server and the open invitations")} />
      <Page>
        <Card>
          <CardHeader><CardTitle>{t("Invite a server admin")}</CardTitle></CardHeader>
          <CardContent>
            <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (email) invite.mutate(); }}>
              <Input type="email" placeholder={t("email address")} className="w-64" value={email} onChange={(e) => setEmail(e.target.value)} aria-label={t("Email")} />
              <Button type="submit" disabled={!email || invite.isPending}>{t("Invite")}</Button>
            </form>
            {note && <Callout kind="warning" className="mt-3">{note}</Callout>}
            <p className="mt-2 text-xs text-muted-foreground">{t("Project members are invited by project admins under the project's Members page.")}</p>
          </CardContent>
        </Card>
        <DataTable columns={userColumns} data={users.data?.items} isLoading={users.isPending} />
        <h2 className="text-base font-medium">{t("Invitations")}</h2>
        <DataTable columns={invitationColumns} data={invitations.data?.items} isLoading={invitations.isPending} emptyMessage={t("No invitations.")} />
      </Page>
    </>
  );
}
