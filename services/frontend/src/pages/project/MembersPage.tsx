import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useParams, useSearchParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Entity,
  EntityGroup,
  Invitation,
  Member,
  MemberScope,
  Page as PageType,
  PermissionCatalogue,
  ProjectRole,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useGroups } from "@/hooks/useGroups";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import {
  areaLabel,
  BUILTIN_ROLES,
  permissionHint,
  permissionLabel,
  roleDescription,
  roleLabel,
} from "@/lib/permissions";

/**
 * Members, roles and invitations of a project (decisions D185 to D188): every member with a
 * role (built in or composed) and what they see (the whole project or a scope of groups,
 * entities and devices), custom roles composed by area, and invitations that carry both.
 */
const inviteSchema = z.object({
  email: z.email("Enter a valid email address"),
  role: z.string().min(1),
});
type InviteValues = z.infer<typeof inviteSchema>;

const CUSTOM = "custom:";
const roleValue = (m: { role: string; role_id?: string | null }) =>
  m.role_id ? `${CUSTOM}${m.role_id}` : m.role;
const roleBody = (value: string) =>
  value.startsWith(CUSTOM)
    ? { role_id: value.slice(CUSTOM.length) }
    : { role: value, role_id: null };

function scopeSummary(scope: MemberScope | null | undefined, t: (k: string, o?: Record<string, unknown>) => string): string {
  const groups = scope?.groups ?? [];
  const entities = scope?.entities ?? [];
  const devices = scope?.devices ?? [];
  if (!groups.length && !entities.length && !devices.length) return t("Everything");
  const parts: string[] = [];
  if (groups.length) parts.push(t("{{count}} groups", { count: groups.length }));
  if (entities.length) parts.push(t("{{count}} entities", { count: entities.length }));
  if (devices.length) parts.push(t("{{count}} devices", { count: devices.length }));
  return parts.join(", ");
}

export function MembersPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "roles" ? "roles" : params.get("tab") === "invitations" ? "invitations" : "members";
  const base = `/api/v1/projects/${projectId}`;
  const members = useQuery({
    queryKey: queryKeys.members(projectId),
    queryFn: () => api.get<PageType<Member>>(`${base}/members`, { query: { limit: 500 } }),
  });
  const invitations = useQuery({
    queryKey: queryKeys.invitations(projectId),
    queryFn: () => api.get<PageType<Invitation>>(`${base}/invitations`, { query: { limit: 500 } }),
  });
  const roles = useQuery({
    queryKey: ["projects", projectId, "roles"],
    queryFn: () => api.get<ProjectRole[]>(`${base}/roles`),
  });
  const catalogue = useQuery({
    queryKey: ["permissions"],
    queryFn: () => api.get<PermissionCatalogue>("/api/v1/permissions"),
    staleTime: Infinity,
  });
  const [removing, setRemoving] = useState<Member | null>(null);
  const [scoping, setScoping] = useState<Member | null>(null);
  const [editingRole, setEditingRole] = useState<ProjectRole | "new" | null>(null);
  const [deletingRole, setDeletingRole] = useState<ProjectRole | null>(null);
  const [inviteScope, setInviteScope] = useState<MemberScope | null>(null);
  const [inviteScoping, setInviteScoping] = useState(false);
  const [lastLink, setLastLink] = useState<string | null>(null);
  const form = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "project-viewer" },
  });

  const roleOptions = useMemo(
    () => [
      ...BUILTIN_ROLES.map((r) => ({ value: r, label: roleLabel(r) })),
      ...(roles.data ?? []).map((r) => ({ value: `${CUSTOM}${r.id}`, label: r.name })),
    ],
    [roles.data],
  );
  const roleNameOf = (value: string) => roleOptions.find((o) => o.value === value)?.label ?? value;

  const invite = useMutationToast({
    mutationFn: (values: InviteValues) =>
      api.post<Invitation>(`${base}/invitations`, {
        body: { email: values.email, ...roleBody(values.role), scope: inviteScope },
      }),
    invalidate: [queryKeys.invitations(projectId)],
    onSuccess: (data) => {
      form.reset();
      setInviteScope(null);
      setLastLink(
        data.mail_sent
          ? null
          : t("The invitation was not mailed ({{reason}}). Share this registration link with the person instead: {{link}}", {
              reason: data.mail_reason ?? t("unknown reason"),
              link: data.registration_link ?? "",
            }),
      );
    },
    success: (data) => (data.mail_sent ? t("Invitation sent") : t("Invitation created")),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const changeMember = useMutationToast({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<Member>(`${base}/members/${id}`, { body }),
    invalidate: [queryKeys.members(projectId), ["projects", projectId, "roles"]],
    success: t("Member updated"),
    onSuccess: () => setScoping(null),
  });
  const remove = useMutationToast({
    mutationFn: (id: string) => api.delete(`${base}/members/${id}`),
    invalidate: [queryKeys.members(projectId), ["projects", projectId, "roles"]],
    success: t("Member removed"),
    onSuccess: () => setRemoving(null),
  });
  const revoke = useMutationToast({
    mutationFn: (id: string) => api.delete(`${base}/invitations/${id}`),
    invalidate: [queryKeys.invitations(projectId)],
    success: t("Invitation revoked"),
  });
  const saveRole = useMutationToast({
    mutationFn: ({ id, body }: { id: string | null; body: Record<string, unknown> }) =>
      id
        ? api.patch<ProjectRole>(`${base}/roles/${id}`, { body })
        : api.post<ProjectRole>(`${base}/roles`, { body }),
    invalidate: [["projects", projectId, "roles"], queryKeys.members(projectId)],
    success: t("Role saved"),
    onSuccess: () => setEditingRole(null),
  });
  const deleteRole = useMutationToast({
    mutationFn: (id: string) => api.delete(`${base}/roles/${id}`),
    invalidate: [["projects", projectId, "roles"]],
    success: t("Role deleted"),
    onSuccess: () => setDeletingRole(null),
  });

  const memberColumns: ColumnDef<Member, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Name"), accessorKey: "full_name" },
    {
      header: t("Role"),
      accessorKey: "role_name",
      cell: ({ row }) => (
        <Select
          value={roleValue(row.original)}
          onValueChange={(value) => changeMember.mutate({ id: row.original.id, body: roleBody(value) })}
        >
          <SelectTrigger className="h-8 w-44" aria-label={t("Role of {{email}}", { email: row.original.email })}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roleOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ),
    },
    {
      header: t("Sees"),
      id: "scope",
      cell: ({ row }) => (
        <button
          type="button"
          className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-primary"
          title={t("Change what this member sees")}
          onClick={(e) => { e.stopPropagation(); setScoping(row.original); }}
        >
          {scopeSummary(row.original.scope, t)}
          <Pencil className="size-3.5 text-muted-foreground" />
        </button>
      ),
    },
    { header: t("Since"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button variant="ghost" size="icon" aria-label={t("Remove member")} onClick={(e) => { e.stopPropagation(); setRemoving(row.original); }}>
          <Trash2 className="size-4" />
        </Button>
      ),
    },
  ];
  const invitationColumns: ColumnDef<Invitation, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Role"), id: "role", cell: ({ row }) => roleNameOf(roleValue({ role: row.original.role ?? "", role_id: row.original.role_id })) },
    { header: t("Sees"), id: "scope", cell: ({ row }) => scopeSummary(row.original.scope, t) },
    { header: t("Expires"), accessorKey: "expires_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Used"), accessorKey: "used_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) || t("not yet") },
    { id: "actions", header: "", cell: ({ row }) => (row.original.used_at ? null : <Button variant="ghost" size="sm" onClick={() => revoke.mutate(row.original.id)}>{t("Revoke")}</Button>) },
  ];

  return (
    <>
      <PageHeader
        title={t("Members")}
        description={t("Who can open this project, what each may do (their role) and what each sees (their scope)")}
      />
      <Page>
        <Tabs
          value={tab}
          onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}
        >
          <TabsList>
            <TabsTrigger value="members">{t("Members")}</TabsTrigger>
            <TabsTrigger value="roles">{t("Roles")}</TabsTrigger>
            <TabsTrigger value="invitations">{t("Invitations")}</TabsTrigger>
          </TabsList>
        </Tabs>
        {tab === "members" && (
          <DataTable
            columns={memberColumns}
            data={members.data?.items}
            defaultHiddenSmall={["full_name", "created_at"]}
            searchable
            isLoading={members.isPending}
            emptyMessage={t("No members yet. Invite someone under Invitations.")}
            footer={members.data && t("{{count}} members", { count: members.data.items.length })}
          />
        )}
        {tab === "roles" && (
          <RolesTab
            catalogue={catalogue.data}
            roles={roles.data ?? []}
            onNew={() => setEditingRole("new")}
            onEdit={setEditingRole}
            onDelete={setDeletingRole}
          />
        )}
        {tab === "invitations" && (
          <>
            <Card>
              <CardHeader><CardTitle>{t("Invite someone")}</CardTitle></CardHeader>
              <CardContent>
                <form className="flex flex-wrap items-end gap-3" onSubmit={form.handleSubmit((v) => invite.mutate(v))} noValidate>
                  <Field label={t("Email")} htmlFor="invite-email" error={form.formState.errors.email?.message}>
                    <Input id="invite-email" type="email" className="w-64" {...form.register("email")} />
                  </Field>
                  <Field label={t("Role")} htmlFor="invite-role">
                    <Select value={form.watch("role")} onValueChange={(v) => form.setValue("role", v)}>
                      <SelectTrigger id="invite-role" className="w-44"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {roleOptions.map((o) => (
                          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label={t("Sees")} htmlFor="invite-scope">
                    <Button id="invite-scope" type="button" variant="outline" onClick={() => setInviteScoping(true)}>
                      {scopeSummary(inviteScope, t)}
                    </Button>
                  </Field>
                  <Button type="submit" disabled={invite.isPending}>{t("Send invitation")}</Button>
                </form>
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("The role says what the person may do, the scope what they see; both can be changed later under Members.")}
                </p>
                {form.formState.errors.root && <Callout kind="error" className="mt-3">{form.formState.errors.root.message}</Callout>}
                {lastLink && <Callout kind="warning" className="mt-3">{lastLink}</Callout>}
              </CardContent>
            </Card>
            <DataTable columns={invitationColumns} data={invitations.data?.items} defaultHiddenSmall={["expires_at", "used_at"]} searchable isLoading={invitations.isPending} emptyMessage={t("No invitations.")} />
          </>
        )}
      </Page>
      <ConfirmDialog
        open={removing != null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("Remove member")}
        description={t("{{email}} loses access to this project.", { email: removing?.email ?? "" })}
        confirmLabel={t("Remove")}
        onConfirm={() => removing && remove.mutate(removing.id)}
        pending={remove.isPending}
      />
      <ConfirmDialog
        open={deletingRole != null}
        onOpenChange={(o) => !o && setDeletingRole(null)}
        title={t("Delete role")}
        description={t("The role {{name}} is deleted; a role in use cannot be deleted.", { name: deletingRole?.name ?? "" })}
        confirmLabel={t("Delete")}
        onConfirm={() => deletingRole && deleteRole.mutate(deletingRole.id)}
        pending={deleteRole.isPending}
      />
      {(scoping || inviteScoping) && (
        <ScopeDialog
          projectId={projectId}
          title={scoping ? t("What {{email}} sees", { email: scoping.email }) : t("What the invited person sees")}
          value={scoping ? (scoping.scope ?? null) : inviteScope}
          pending={changeMember.isPending}
          onClose={() => { setScoping(null); setInviteScoping(false); }}
          onSave={(scope) => {
            if (scoping) changeMember.mutate({ id: scoping.id, body: { scope } });
            else { setInviteScope(scope); setInviteScoping(false); }
          }}
        />
      )}
      {editingRole && catalogue.data && (
        <RoleDialog
          catalogue={catalogue.data}
          role={editingRole === "new" ? null : editingRole}
          pending={saveRole.isPending}
          onClose={() => setEditingRole(null)}
          onSave={(body) => saveRole.mutate({ id: editingRole === "new" ? null : editingRole.id, body })}
        />
      )}
    </>
  );
}

/** The built-in roles with their grants, and the project's own roles with edit and delete. */
function RolesTab({
  catalogue,
  roles,
  onNew,
  onEdit,
  onDelete,
}: {
  catalogue: PermissionCatalogue | undefined;
  roles: ProjectRole[];
  onNew: () => void;
  onEdit: (role: ProjectRole) => void;
  onDelete: (role: ProjectRole) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {t("A role is a named set of permissions. The four built-in roles exist on every server; compose your own from the same permissions when none fits.")}
        </p>
        <Button size="sm" onClick={onNew}><Plus className="size-4" /> {t("New role")}</Button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {(catalogue?.roles ?? []).map((role) => (
          <Card key={role.key}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {roleLabel(role.key)}
                <Badge variant="outline">{t("built in")}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p className="text-muted-foreground">{roleDescription(role.key)}</p>
              <div className="flex flex-wrap gap-1">
                {role.permissions.map((p) => (
                  <Badge key={p} variant="secondary" className="font-normal">{permissionLabel(p)}</Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
        {roles.map((role) => (
          <Card key={role.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {role.name}
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" size="icon" aria-label={t("Edit role")} onClick={() => onEdit(role)}><Pencil className="size-4" /></Button>
                  <Button variant="ghost" size="icon" aria-label={t("Delete role")} disabled={role.members > 0} title={role.members > 0 ? t("{{count}} members hold this role", { count: role.members }) : undefined} onClick={() => onDelete(role)}><Trash2 className="size-4" /></Button>
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {role.description && <p className="text-muted-foreground">{role.description}</p>}
              <div className="flex flex-wrap gap-1">
                {role.permissions.map((p) => (
                  <Badge key={p} variant="secondary" className="font-normal">{permissionLabel(p)}</Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{t("{{count}} members", { count: role.members })}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

/** Compose a role: a name, a line of description, the permissions by area. */
function RoleDialog({
  catalogue,
  role,
  pending,
  onClose,
  onSave,
}: {
  catalogue: PermissionCatalogue;
  role: ProjectRole | null;
  pending: boolean;
  onClose: () => void;
  onSave: (body: { name: string; description: string | null; permissions: string[] }) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [chosen, setChosen] = useState<Set<string>>(new Set(role?.permissions ?? ["project:read"]));
  const toggle = (key: string) =>
    setChosen((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      next.add("project:read");
      return next;
    });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{role ? t("Edit role") : t("New role")}</DialogTitle>
          <DialogDescription>{t("Tick what a member with this role may do. Seeing the project is always in.")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label={t("Name")} htmlFor="role-name">
            <Input id="role-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <Field label={t("Description")} htmlFor="role-description">
            <Textarea id="role-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            {catalogue.areas.map((area) => (
              <fieldset key={area.key} className="rounded-md border p-3">
                <legend className="px-1 text-sm font-medium">{areaLabel(area.key)}</legend>
                <div className="space-y-2">
                  {area.permissions.map((key) => (
                    <label key={key} className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1 accent-primary"
                        checked={chosen.has(key)}
                        disabled={key === "project:read"}
                        onChange={() => toggle(key)}
                      />
                      <span>
                        <span className="block">{permissionLabel(key)}</span>
                        <span className="block text-xs text-muted-foreground">{permissionHint(key)}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>{t("Cancel")}</Button>
          <Button
            type="button"
            disabled={pending || name.trim().length === 0}
            onClick={() => onSave({ name: name.trim(), description: description.trim() || null, permissions: [...chosen] })}
          >
            {t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Pick what a member sees: groups (with everything below), entities and devices. */
function ScopeDialog({
  projectId,
  title,
  value,
  pending,
  onClose,
  onSave,
}: {
  projectId: string;
  title: string;
  value: MemberScope | null;
  pending: boolean;
  onClose: () => void;
  onSave: (scope: MemberScope | null) => void;
}) {
  const { t } = useTranslation();
  const groups = useGroups(projectId);
  const entities = useQuery({
    queryKey: ["projects", projectId, "entities", "scope-picker"],
    queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }),
  });
  const devices = useQuery({
    queryKey: ["devices", projectId, "scope-picker"],
    queryFn: () => api.get<PageType<Device>>("/api/v1/devices", { query: { project_id: projectId, limit: 500 } }),
  });
  const [chosenGroups, setChosenGroups] = useState<Set<string>>(new Set(value?.groups ?? []));
  const [chosenEntities, setChosenEntities] = useState<Set<string>>(new Set(value?.entities ?? []));
  const [chosenDevices, setChosenDevices] = useState<Set<string>>(new Set(value?.devices ?? []));
  const [term, setTerm] = useState("");
  const flip = (set: Set<string>, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };
  const tree = useMemo(() => orderTree(groups.data ?? []), [groups.data]);
  const lower = term.toLowerCase();
  const entityRows = (entities.data?.items ?? []).filter((e) => !lower || e.name.toLowerCase().includes(lower));
  const deviceRows = (devices.data?.items ?? []).filter((d) => !lower || d.name.toLowerCase().includes(lower));
  const nothing = chosenGroups.size + chosenEntities.size + chosenDevices.size === 0;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {t("Nothing ticked means the whole project. A ticked group brings everything below it; a ticked entity brings the device tracking it.")}
          </DialogDescription>
        </DialogHeader>
        <Input placeholder={t("Search entities and devices…")} value={term} onChange={(e) => setTerm(e.target.value)} />
        <div className="grid gap-4 sm:grid-cols-3">
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Groups")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {tree.map(({ group, depth }) => (
                <label key={group.id} className="flex items-center gap-2" style={{ paddingLeft: depth * 12 }}>
                  <input type="checkbox" className="accent-primary" checked={chosenGroups.has(group.id)} onChange={() => setChosenGroups((s) => flip(s, group.id))} />
                  <span className="truncate">{group.name}</span>
                </label>
              ))}
              {tree.length === 0 && <p className="text-muted-foreground">{t("No groups.")}</p>}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Entities")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {entityRows.map((e) => (
                <label key={e.id} className="flex items-center gap-2">
                  <input type="checkbox" className="accent-primary" checked={chosenEntities.has(e.id)} onChange={() => setChosenEntities((s) => flip(s, e.id))} />
                  <span className="truncate">{e.name}</span>
                </label>
              ))}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Devices")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {deviceRows.map((d) => (
                <label key={d.id} className="flex items-center gap-2">
                  <input type="checkbox" className="accent-primary" checked={chosenDevices.has(d.id)} onChange={() => setChosenDevices((s) => flip(s, d.id))} />
                  <span className="truncate">{d.name}</span>
                </label>
              ))}
            </div>
          </section>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => { setChosenGroups(new Set()); setChosenEntities(new Set()); setChosenDevices(new Set()); }}>
            {t("Everything")}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>{t("Cancel")}</Button>
          <Button
            type="button"
            disabled={pending}
            onClick={() =>
              onSave(nothing ? null : { groups: [...chosenGroups], entities: [...chosenEntities], devices: [...chosenDevices] })
            }
          >
            {t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The groups as a flat list in tree order with the depth of each. */
function orderTree(groups: EntityGroup[]): { group: EntityGroup; depth: number }[] {
  const byParent = new Map<string | null, EntityGroup[]>();
  for (const g of groups) {
    const key = g.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), g]);
  }
  const out: { group: EntityGroup; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const g of byParent.get(parent) ?? []) {
      out.push({ group: g, depth });
      walk(g.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}
