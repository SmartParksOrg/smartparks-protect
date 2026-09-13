import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeft, KeyRound, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { UserAdminDetail, UserAdminMembership } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { roleBody, roleValue, scopeSummary } from "@/components/members/roles";
import { RoleSelect } from "@/components/members/RoleSelect";
import { ScopeDialog } from "@/components/members/scope";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useProjects } from "@/hooks/useProjects";
import { formatAgo, formatTime } from "@/lib/format";
import { BUILTIN_ROLES } from "@/lib/permissions";
import { useAuthStore } from "@/stores/auth";

/**
 * One account as the server admin manages it (decision D189): the account itself (email, name,
 * active, server admin, a password reset mail) and its memberships across every project, each
 * with the role and the scope editable in place, plus adding the person to another project.
 * The role and scope pieces are the ones the project's Members page uses.
 */
export function UserPage() {
  const { t } = useTranslation();
  const { userId = "" } = useParams();
  const me = useAuthStore((s) => s.user);
  const projects = useProjects();
  const user = useQuery({
    queryKey: queryKeys.user(userId),
    queryFn: () => api.get<UserAdminDetail>(`/api/v1/admin/users/${userId}`),
    enabled: !!userId,
  });
  const invalidate = [queryKeys.user(userId), queryKeys.users];
  const update = useMutationToast({
    mutationFn: (body: Record<string, unknown>) => api.patch<UserAdminDetail>(`/api/v1/admin/users/${userId}`, { body }),
    invalidate,
    success: t("User updated"),
  });
  const reset = useMutationToast({
    mutationFn: () => api.post(`/api/v1/admin/users/${userId}/password-reset`),
    success: t("Password reset mail sent"),
  });
  const changeMember = useMutationToast({
    mutationFn: ({ m, body }: { m: UserAdminMembership; body: Record<string, unknown> }) =>
      api.patch(`/api/v1/projects/${m.project_id}/members/${m.membership_id}`, { body }),
    invalidate,
    success: t("Membership updated"),
    onSuccess: () => setScoping(null),
  });
  const remove = useMutationToast({
    mutationFn: (m: UserAdminMembership) => api.delete(`/api/v1/projects/${m.project_id}/members/${m.membership_id}`),
    invalidate: [...invalidate, queryKeys.projects],
    success: t("Membership removed"),
    onSuccess: () => setRemoving(null),
  });
  const [addProject, setAddProject] = useState("");
  const [addRole, setAddRole] = useState<string>(BUILTIN_ROLES[0]);
  const add = useMutationToast({
    mutationFn: () =>
      api.post(`/api/v1/projects/${addProject}/members`, { body: { email: user.data?.email, ...roleBody(addRole) } }),
    invalidate: [...invalidate, queryKeys.members(addProject)],
    success: t("Added to the project"),
    onSuccess: () => { setAddProject(""); setAddRole(BUILTIN_ROLES[0]); },
  });
  const [scoping, setScoping] = useState<UserAdminMembership | null>(null);
  const [removing, setRemoving] = useState<UserAdminMembership | null>(null);

  const memberOf = useMemo(() => new Set((user.data?.memberships ?? []).map((m) => m.project_id)), [user.data]);
  const openProjects = (projects.data?.items ?? []).filter((p) => !memberOf.has(p.id));
  const isMe = user.data?.id === me?.id;

  const columns: ColumnDef<UserAdminMembership, unknown>[] = [
    {
      header: t("Project"),
      accessorKey: "project_name",
      cell: ({ row }) => (
        <Link className="underline-offset-2 hover:underline" to={`/projects/${row.original.project_id}/admin/members`}>
          {row.original.project_name}
        </Link>
      ),
    },
    {
      header: t("Role"),
      accessorKey: "role_name",
      cell: ({ row }) => <MembershipRole membership={row.original} onChange={(body) => changeMember.mutate({ m: row.original, body })} />,
    },
    {
      header: t("Sees"),
      id: "scope",
      cell: ({ row }) => (
        <Button variant="ghost" size="sm" className="h-8" onClick={() => setScoping(row.original)} title={t("Change what this member sees")}>
          {scopeSummary(row.original.scope, t)}
        </Button>
      ),
    },
    { header: t("Since"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button variant="ghost" size="icon" className="size-8" onClick={() => setRemoving(row.original)} aria-label={t("Remove from {{project}}", { project: row.original.project_name })}>
          <Trash2 className="size-4" />
        </Button>
      ),
    },
  ];

  const u = user.data;
  return (
    <>
      <PageHeader
        title={u?.full_name || u?.email || t("User")}
        description={u?.full_name ? u.email : undefined}
        leading={
          <Button variant="ghost" size="icon" className="size-8" asChild>
            <Link to="/admin/users" aria-label={t("Back to users")}><ArrowLeft className="size-4" /></Link>
          </Button>
        }
        actions={
          <Button variant="outline" size="sm" disabled={!u?.is_active || reset.isPending} onClick={() => reset.mutate()}>
            <KeyRound className="size-4" />
            {t("Send password reset")}
          </Button>
        }
      />
      <Page>
        {user.isError && <p className="text-sm text-destructive">{user.error.message}</p>}
        {u && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
            <Card>
              <CardHeader><CardTitle>{t("Account")}</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-4">
                <AccountField id="user-email" label={t("Email")} type="email" value={u.email} onSave={(email) => update.mutate({ email })} pending={update.isPending} />
                <AccountField id="user-name" label={t("Name")} value={u.full_name ?? ""} onSave={(full_name) => update.mutate({ full_name })} pending={update.isPending} />
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm">{t("Active")}</span>
                  <Switch checked={u.is_active} disabled={isMe || update.isPending} onCheckedChange={(v) => update.mutate({ is_active: v })} aria-label={t("Active")} />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm">{t("Server admin")}</span>
                  <Switch checked={u.is_superuser} disabled={isMe || update.isPending} onCheckedChange={(v) => update.mutate({ is_superuser: v })} aria-label={t("Server admin")} />
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  <dt className="text-muted-foreground">{t("Last login")}</dt>
                  <dd>{formatAgo(u.last_login_at) || t("never")}</dd>
                  <dt className="text-muted-foreground">{t("Created")}</dt>
                  <dd>{formatTime(u.created_at)}</dd>
                </dl>
                {isMe && <p className="text-xs text-muted-foreground">{t("Your own active and server admin flags are changed by another server admin.")}</p>}
              </CardContent>
            </Card>
            <div className="flex min-w-0 flex-col gap-4">
              <Card>
                <CardHeader><CardTitle>{t("Add to a project")}</CardTitle></CardHeader>
                <CardContent>
                  <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (addProject) add.mutate(); }}>
                    <Field label={t("Project")} htmlFor="add-project">
                      <Select value={addProject} onValueChange={setAddProject}>
                        <SelectTrigger id="add-project" className="w-56"><SelectValue placeholder={t("Choose a project")} /></SelectTrigger>
                        <SelectContent>
                          {openProjects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label={t("Role")} htmlFor="add-role">
                      <RoleSelect id="add-role" projectId={addProject || null} value={addRole} onChange={setAddRole} />
                    </Field>
                    <Button type="submit" disabled={!addProject || add.isPending}>{t("Add")}</Button>
                  </form>
                  {openProjects.length === 0 && projects.data && (
                    <p className="mt-2 text-xs text-muted-foreground">{t("This person is a member of every project.")}</p>
                  )}
                </CardContent>
              </Card>
              <h2 className="text-base font-medium">{t("Memberships")}</h2>
              <DataTable columns={columns} data={u.memberships} isLoading={user.isPending} emptyMessage={t("No project memberships yet.")} defaultHiddenSmall={["created_at"]} />
            </div>
          </div>
        )}
      </Page>
      <ConfirmDialog
        open={removing != null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("Remove membership")}
        description={t("{{email}} loses access to {{project}}.", { email: u?.email ?? "", project: removing?.project_name ?? "" })}
        confirmLabel={t("Remove")}
        onConfirm={() => removing && remove.mutate(removing)}
        pending={remove.isPending}
      />
      {scoping && (
        <ScopeDialog
          projectId={scoping.project_id}
          title={t("What {{email}} sees in {{project}}", { email: u?.email ?? "", project: scoping.project_name })}
          value={scoping.scope ?? null}
          pending={changeMember.isPending}
          onClose={() => setScoping(null)}
          onSave={(scope) => changeMember.mutate({ m: scoping, body: { scope } })}
        />
      )}
    </>
  );
}

/** A text field with its own Save button, so the email and the name change one at a time. */
function AccountField({ id, label, type = "text", value, onSave, pending }: { id: string; label: string; type?: string; value: string; onSave: (value: string) => void; pending: boolean }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<string | null>(null);
  const current = draft ?? value;
  const changed = draft != null && draft !== value;
  return (
    <form className="flex flex-col gap-1.5" onSubmit={(e) => { e.preventDefault(); if (changed) { onSave(current.trim()); setDraft(null); } }}>
      <Field label={label} htmlFor={id}>
        <div className="flex gap-2">
          <Input id={id} type={type} value={current} onChange={(e) => setDraft(e.target.value)} required={type === "email"} />
          <Button type="submit" variant="outline" disabled={!changed || pending}>{t("Save")}</Button>
        </div>
      </Field>
    </form>
  );
}

/** The role select of one membership: the built-in roles and the project's custom roles. */
function MembershipRole({ membership, onChange }: { membership: UserAdminMembership; onChange: (body: Record<string, unknown>) => void }) {
  return <RoleSelect projectId={membership.project_id} value={roleValue(membership)} onChange={(v) => onChange(roleBody(v))} className="h-8 w-44" />;
}
