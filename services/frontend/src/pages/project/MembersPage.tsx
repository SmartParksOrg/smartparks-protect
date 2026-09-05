import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Invitation, Member, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const inviteSchema = z.object({ email: z.email("Enter a valid email address"), role: z.enum(["project-viewer", "project-admin"]) });
type InviteValues = z.infer<typeof inviteSchema>;

export function MembersPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const members = useQuery({ queryKey: queryKeys.members(projectId), queryFn: () => api.get<PageType<Member>>(`/api/v1/projects/${projectId}/members`, { query: { limit: 500 } }) });
  const invitations = useQuery({ queryKey: queryKeys.invitations(projectId), queryFn: () => api.get<PageType<Invitation>>(`/api/v1/projects/${projectId}/invitations`, { query: { limit: 500 } }) });
  const [removing, setRemoving] = useState<Member | null>(null);
  const [lastLink, setLastLink] = useState<string | null>(null);
  const form = useForm<InviteValues>({ resolver: zodResolver(inviteSchema), defaultValues: { email: "", role: "project-viewer" } });

  const invite = useMutationToast({
    mutationFn: (values: InviteValues) => api.post<Invitation & { mail_sent: boolean }>(`/api/v1/projects/${projectId}/invitations`, { body: values }),
    invalidate: [queryKeys.invitations(projectId)],
    onSuccess: (data) => {
      form.reset();
      setLastLink(data.mail_sent ? null : `Mail is not configured on this server. Share the registration link from the server log, or configure SMTP. Invitation id ${data.id}.`);
    },
    success: (data) => (data.mail_sent ? "Invitation sent" : "Invitation created"),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const changeRole = useMutationToast({ mutationFn: ({ id, role }: { id: string; role: string }) => api.patch(`/api/v1/projects/${projectId}/members/${id}`, { body: { role } }), invalidate: [queryKeys.members(projectId)], success: t("Role updated") });
  const remove = useMutationToast({ mutationFn: (id: string) => api.delete(`/api/v1/projects/${projectId}/members/${id}`), invalidate: [queryKeys.members(projectId)], success: t("Member removed"), onSuccess: () => setRemoving(null) });
  const revoke = useMutationToast({ mutationFn: (id: string) => api.delete(`/api/v1/projects/${projectId}/invitations/${id}`), invalidate: [queryKeys.invitations(projectId)], success: t("Invitation revoked") });

  const memberColumns: ColumnDef<Member, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Name"), accessorKey: "full_name" },
    { header: t("Role"), accessorKey: "role", cell: ({ row }) => (
      <Select value={row.original.role} onValueChange={(role) => changeRole.mutate({ id: row.original.id, role })}>
        <SelectTrigger className="h-8 w-40"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="project-viewer">{t("viewer")}</SelectItem><SelectItem value="project-admin">{t("admin")}</SelectItem></SelectContent>
      </Select>
    ) },
    { header: t("Since"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { id: "actions", header: "", cell: ({ row }) => <Button variant="ghost" size="icon" aria-label={t("Remove member")} onClick={(e) => { e.stopPropagation(); setRemoving(row.original); }}><Trash2 className="size-4" /></Button> },
  ];
  const invitationColumns: ColumnDef<Invitation, unknown>[] = [
    { header: t("Email"), accessorKey: "email" },
    { header: t("Role"), accessorKey: "role" },
    { header: t("Expires"), accessorKey: "expires_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Used"), accessorKey: "used_at", cell: ({ getValue }) => formatTime(getValue<string | null>()) || "not yet" },
    { id: "actions", header: "", cell: ({ row }) => (row.original.used_at ? null : <Button variant="ghost" size="sm" onClick={() => revoke.mutate(row.original.id)}>{t("Revoke")}</Button>) },
  ];

  return (
    <>
      <PageHeader title={t("Members")} description={t("Who can open this project and with which role")} />
      <Page>
        <Card>
          <CardHeader><CardTitle>{t("Invite someone")}</CardTitle></CardHeader>
          <CardContent>
            <form className="flex flex-wrap items-end gap-3" onSubmit={form.handleSubmit((v) => invite.mutate(v))} noValidate>
              <Field label={t("Email")} htmlFor="invite-email" error={form.formState.errors.email?.message}><Input id="invite-email" type="email" className="w-64" {...form.register("email")} /></Field>
              <Field label={t("Role")} htmlFor="invite-role">
                <Select value={form.watch("role")} onValueChange={(v) => form.setValue("role", v as InviteValues["role"])}>
                  <SelectTrigger id="invite-role" className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="project-viewer">{t("viewer")}</SelectItem><SelectItem value="project-admin">{t("admin")}</SelectItem></SelectContent>
                </Select>
              </Field>
              <Button type="submit" disabled={invite.isPending}>{t("Send invitation")}</Button>
            </form>
            {form.formState.errors.root && <Callout kind="error" className="mt-3">{form.formState.errors.root.message}</Callout>}
            {lastLink && <Callout kind="warning" className="mt-3">{lastLink}</Callout>}
          </CardContent>
        </Card>
        <DataTable columns={memberColumns} data={members.data?.items} searchable isLoading={members.isPending} emptyMessage={t("No members yet.")} />
        <h2 className="text-base font-medium">{t("Open invitations")}</h2>
        <DataTable columns={invitationColumns} data={invitations.data?.items} searchable isLoading={invitations.isPending} emptyMessage={t("No invitations.")} />
      </Page>
      <ConfirmDialog open={removing != null} onOpenChange={(o) => !o && setRemoving(null)} title={t("Remove member")} description={`${removing?.email} loses access to this project.`} confirmLabel={t("Remove")} onConfirm={() => removing && remove.mutate(removing.id)} pending={remove.isPending} />
    </>
  );
}
