import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Invitation, MemberScope, Page as PageType, ServerInvitationResult, UserAdmin } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { RoleSelect } from "@/components/members/RoleSelect";
import { roleBody, scopeSummary } from "@/components/members/roles";
import { ScopeDialog } from "@/components/members/scope";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjects } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";
import { BUILTIN_ROLES, roleLabel } from "@/lib/permissions";
import { useAuthStore } from "@/stores/auth";

/** A project row of the invite form: the project, the role select's value and the scope. */
interface InviteRow {
  key: number;
  projectId: string;
  role: string;
  scope: MemberScope | null;
}

/**
 * Every account on the server, the invite form and the open invitations. The form invites one
 * person as server admin and/or into any projects at once, each with a role and what they see
 * (decision D190); an address that already has an account gets the memberships straight away.
 */
export function UsersPage() {
  const { t } = useTranslation();
  const me = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const projects = useProjects();
  const users = useQuery({ queryKey: queryKeys.users, queryFn: () => api.get<PageType<UserAdmin>>("/api/v1/admin/users", { query: { limit: 500 } }) });
  const invitations = useQuery({ queryKey: queryKeys.serverInvitations, queryFn: () => api.get<PageType<Invitation>>("/api/v1/admin/invitations", { query: { limit: 500 } }) });
  const projectName = useMemo(() => new Map((projects.data?.items ?? []).map((p) => [p.id, p.name])), [projects.data]);

  const [email, setEmail] = useState("");
  const [serverAdmin, setServerAdmin] = useState(false);
  const [rows, setRows] = useState<InviteRow[]>([]);
  const [scoping, setScoping] = useState<InviteRow | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const known = users.data?.items.find((u) => u.email === email.trim().toLowerCase()) ?? null;
  const complete = rows.every((r) => r.projectId) && (serverAdmin || rows.length > 0);
  const setRow = (key: number, patch: Partial<InviteRow>) => setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const reset = () => { setEmail(""); setServerAdmin(false); setRows([]); };

  const update = useMutationToast({ mutationFn: ({ id, body }: { id: string; body: Record<string, boolean> }) => api.patch(`/api/v1/admin/users/${id}`, { body }), invalidate: [queryKeys.users], success: t("User updated") });
  const invite = useMutationToast({
    mutationFn: () =>
      api.post<ServerInvitationResult>("/api/v1/admin/invitations", {
        body: {
          email: email.trim(),
          server_admin: serverAdmin,
          memberships: rows.map((r) => ({ project_id: r.projectId, ...roleBody(r.role), scope: r.scope })),
        },
      }),
    invalidate: [queryKeys.serverInvitations, queryKeys.users, queryKeys.projects],
    success: (d) => (d.invitation ? (d.invitation.mail_sent ? t("Invitation sent") : t("Invitation created")) : t("Memberships added")),
    onSuccess: (d) => {
      reset();
      if (d.invitation) {
        setNote(d.invitation.mail_sent ? null : t("The invitation was not mailed ({{reason}}). Share this registration link with the person instead: {{link}}", { reason: d.invitation.mail_reason ?? t("unknown reason"), link: d.invitation.registration_link ?? "" }));
      } else {
        setNote((d.added_projects ?? []).length ? t("{{email}} already has an account, so no mail went out: added to {{projects}}.", { email: known?.email ?? "", projects: (d.added_projects ?? []).join(", ") }) : t("{{email}} already has an account and is a member of every project chosen; nothing to add.", { email: known?.email ?? "" }));
      }
    },
  });
  const revoke = useMutationToast({ mutationFn: (id: string) => api.delete(`/api/v1/admin/invitations/${id}`), invalidate: [queryKeys.serverInvitations], success: t("Invitation revoked") });

  const userColumns: ColumnDef<UserAdmin, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Name"), accessorKey: "full_name" },
    { header: t("Active"), accessorKey: "is_active", cell: ({ row }) => <Switch checked={row.original.is_active} disabled={row.original.id === me?.id} onClick={(e) => e.stopPropagation()} onCheckedChange={(v) => update.mutate({ id: row.original.id, body: { is_active: v } })} aria-label={t("Active")} /> },
    { header: t("Server admin"), accessorKey: "is_superuser", cell: ({ row }) => <Switch checked={row.original.is_superuser} disabled={row.original.id === me?.id} onClick={(e) => e.stopPropagation()} onCheckedChange={(v) => update.mutate({ id: row.original.id, body: { is_superuser: v } })} aria-label={t("Server admin")} /> },
    { header: t("Last login"), accessorKey: "last_login_at", cell: ({ getValue }) => formatAgo(getValue<string | null>()) },
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
  ];
  const invitationKind = (i: Invitation): string => {
    const parts: string[] = [];
    if (i.server_admin) parts.push(t("server admin"));
    if (i.project_id) parts.push(`${projectName.get(i.project_id) ?? t("a project")} (${roleLabel(i.role ?? "")})`);
    for (const m of i.memberships ?? []) parts.push(`${projectName.get(m.project_id) ?? t("a project")} (${m.role_id ? t("custom role") : roleLabel(m.role ?? "")})`);
    return parts.join(", ");
  };
  const invitationColumns: ColumnDef<Invitation, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Invited as"), id: "kind", accessorFn: invitationKind },
    { header: t("Expires"), accessorKey: "expires_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Used"), accessorKey: "used_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) || t("not yet") },
    { id: "actions", header: "", cell: ({ row }) => (row.original.used_at ? null : <Button variant="ghost" size="sm" onClick={() => revoke.mutate(row.original.id)}>{t("Revoke")}</Button>) },
  ];
  return (
    <>
      <PageHeader title={t("Users")} description={t("Every account on this server and the open invitations")} />
      <Page>
        <Card>
          <CardHeader><CardTitle>{t("Invite a person")}</CardTitle></CardHeader>
          <CardContent>
            <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (email && complete) invite.mutate(); }}>
              <div className="flex flex-wrap items-center gap-3">
                <Input type="email" placeholder={t("email address")} className="w-64" value={email} onChange={(e) => setEmail(e.target.value)} aria-label={t("Email")} />
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="accent-primary" checked={serverAdmin} onChange={(e) => setServerAdmin(e.target.checked)} />
                  {t("Server admin")}
                </label>
              </div>
              {rows.map((row) => (
                <div key={row.key} className="flex flex-wrap items-center gap-2">
                  <Select value={row.projectId} onValueChange={(v) => setRow(row.key, { projectId: v, role: BUILTIN_ROLES[0], scope: null })}>
                    <SelectTrigger className="w-56" aria-label={t("Project")}><SelectValue placeholder={t("Choose a project")} /></SelectTrigger>
                    <SelectContent>
                      {(projects.data?.items ?? []).filter((p) => p.id === row.projectId || !rows.some((r) => r.projectId === p.id)).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <RoleSelect projectId={row.projectId || null} value={row.role} onChange={(v) => setRow(row.key, { role: v })} />
                  <Button type="button" variant="ghost" size="sm" disabled={!row.projectId} onClick={() => setScoping(row)} title={t("Change what this member sees")}>
                    {t("Sees")}: {scopeSummary(row.scope, t)}
                  </Button>
                  <Button type="button" variant="ghost" size="icon" className="size-8" onClick={() => setRows((all) => all.filter((r) => r.key !== row.key))} aria-label={t("Remove this project")}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="button" variant="outline" size="sm" onClick={() => setRows((all) => [...all, { key: Date.now() + all.length, projectId: "", role: BUILTIN_ROLES[0], scope: null }])} disabled={rows.length >= (projects.data?.items.length ?? 0)}>
                  <Plus className="size-4" />
                  {t("Add a project")}
                </Button>
                <Button type="submit" disabled={!email || !complete || invite.isPending}>{known ? t("Add to projects") : t("Invite")}</Button>
                {known && (
                  <span className="text-xs text-muted-foreground">
                    {t("This address already has an account; the memberships are added right away.")} <Link className="underline" to={`/admin/users/${known.id}`}>{t("Open the account")}</Link>
                  </span>
                )}
              </div>
            </form>
            {note && <Callout kind="warning" className="mt-3">{note}</Callout>}
            <p className="mt-2 text-xs text-muted-foreground">{t("One mail with one link; registration creates every membership. Project admins invite for their own project under the project's Members page. Open an account below to manage its memberships, name, email and password.")}</p>
          </CardContent>
        </Card>
        <DataTable columns={userColumns} data={users.data?.items} searchable isLoading={users.isPending} onRowClick={(u) => void navigate(`/admin/users/${u.id}`)} />
        <h2 className="text-base font-medium">{t("Invitations")}</h2>
        <DataTable columns={invitationColumns} data={invitations.data?.items} searchable isLoading={invitations.isPending} emptyMessage={t("No invitations.")} defaultHiddenSmall={["expires_at"]} />
      </Page>
      {scoping && (
        <ScopeDialog
          projectId={scoping.projectId}
          title={t("What the invited person sees in {{project}}", { project: projectName.get(scoping.projectId) ?? "" })}
          value={scoping.scope}
          pending={false}
          onClose={() => setScoping(null)}
          onSave={(scope) => { setRow(scoping.key, { scope }); setScoping(null); }}
        />
      )}
    </>
  );
}
