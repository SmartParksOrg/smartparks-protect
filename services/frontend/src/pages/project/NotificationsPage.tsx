import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy, Plus, RefreshCw, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { NotificationCapabilities, NotificationTarget, Page as PageType } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import { type Scope, scopeBase } from "@/lib/rules";

const schema = z.object({ name: z.string().min(1).max(200), channel: z.enum(["email", "telegram"]), address: z.string(), enabled: z.boolean() }).refine((v) => v.channel !== "email" || v.address.includes("@"), { path: ["address"], message: "An email address is needed" });
type Values = z.infer<typeof schema>;

/** Notification targets of a project or of the server: email addresses and Telegram chats linked with a code (decision D43). */
export function NotificationsPage({ scope: scopeProp }: { scope?: Scope } = {}) {
  const { projectId = "" } = useParams();
  const scope = scopeProp ?? projectId;
  const base = `${scopeBase(scope)}/notification-targets`;
  const targets = useQuery({ queryKey: queryKeys.notificationTargets(scope), queryFn: () => api.get<PageType<NotificationTarget>>(base, { query: { limit: 500 } }) });
  const caps = useQuery({ queryKey: queryKeys.notificationCapabilities(scope), queryFn: () => api.get<NotificationCapabilities>(`${scopeBase(scope)}/notifications/capabilities`) });
  const [editing, setEditing] = useState<NotificationTarget | null>(null);
  const [open, setOpen] = useState(false);
  const [linking, setLinking] = useState<NotificationTarget | null>(null);
  const [removing, setRemoving] = useState<NotificationTarget | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", channel: "email", address: "", enabled: true } });
  useEffect(() => { if (open) form.reset(editing ? { name: editing.name, channel: editing.channel as "email" | "telegram", address: editing.address ?? "", enabled: editing.enabled } : { name: "", channel: "email", address: "", enabled: true }); }, [open, editing, form]);
  const invalidate = [queryKeys.notificationTargets(scope)];
  const save = useMutationToast({
    mutationFn: (v: Values) => (editing ? api.patch<NotificationTarget>(`${base}/${editing.id}`, { body: { name: v.name, address: v.channel === "email" ? v.address : null, enabled: v.enabled } }) : api.post<NotificationTarget>(base, { body: { name: v.name, channel: v.channel, address: v.channel === "email" ? v.address : null, enabled: v.enabled } })),
    invalidate,
    success: editing ? "Target saved" : "Target created",
    onSuccess: (t) => { setOpen(false); if (!editing && t.channel === "telegram") setLinking(t); },
    onError: (e) => form.setError("root", { message: e.message }),
  });
  const relink = useMutationToast({ mutationFn: (t: NotificationTarget) => api.post<NotificationTarget>(`${base}/${t.id}/link-code`), invalidate, onSuccess: (t) => setLinking(t) });
  const test = useMutationToast({
    mutationFn: (t: NotificationTarget) => api.post<{ status: string; detail: string | null }>(`${base}/${t.id}/test`),
    onSuccess: (r) => (r.status === "sent" ? toast.success("Test message sent") : r.status === "skipped" ? toast.info(`Not sent: ${r.detail}`) : toast.error(`Failed: ${r.detail}`)),
  });
  const remove = useMutationToast({ mutationFn: (t: NotificationTarget) => api.delete<void>(`${base}/${t.id}`), invalidate, success: "Target deleted", onSuccess: () => setRemoving(null) });

  const columns: ColumnDef<NotificationTarget, unknown>[] = [
    { header: "Name", accessorKey: "name" },
    { header: "Channel", accessorKey: "channel" },
    { header: "Address", id: "address", cell: ({ row }) => row.original.channel === "email" ? row.original.address : row.original.linked ? "chat linked" : <span className="text-brand-sand">not linked</span> },
    { header: "Enabled", accessorKey: "enabled", cell: ({ getValue }) => <StatusBadge value={getValue<boolean>() ? "enabled" : "disabled"} /> },
    { header: "Updated", accessorKey: "updated_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { id: "actions", header: "", cell: ({ row }) => (
        <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {row.original.channel === "telegram" && <Button variant="ghost" size="sm" onClick={() => (row.original.telegram_link_code ? setLinking(row.original) : relink.mutate(row.original))}><RefreshCw className="size-4" /> {row.original.linked ? "Relink" : "Link code"}</Button>}
          <Button variant="ghost" size="sm" onClick={() => test.mutate(row.original)} disabled={test.isPending}><Send className="size-4" /> Test</Button>
          <Button variant="ghost" size="icon" aria-label="Delete target" onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button>
        </span>
      ) },
  ];
  const channel = form.watch("channel");

  return (
    <>
      <PageHeader title="Notifications" description={scope === "server" ? "Where system alerts go: server-level targets used by server-level automations" : "Where this project's automations deliver: email addresses and Telegram chats"} actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> New target</Button>} />
      <Page>
        {caps.data && !caps.data.mail_configured && <Callout kind="warning">Mail is not configured on this server (MAIL_SERVER and friends in the environment). Email notifications are logged, not sent.</Callout>}
        {caps.data && !caps.data.telegram_configured && <Callout kind="info">Telegram is not configured (TELEGRAM_BOT_TOKEN). Telegram targets can be created but cannot be linked or reached.</Callout>}
        {targets.error && <Callout kind="error">{targets.error.message}</Callout>}
        <DataTable columns={columns} data={targets.data?.items} isLoading={targets.isPending} emptyMessage="No targets yet. Add an email address or a Telegram chat, then use it in an automation." onRowClick={(t) => { setEditing(t); setOpen(true); }} />
      </Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? "Edit target" : "New target"}</DialogTitle><DialogDescription>A Telegram target gets a code; send it to the bot from the chat that should receive alerts.</DialogDescription></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <Field label="Name" htmlFor="nt-name" error={form.formState.errors.name?.message}><Input id="nt-name" {...form.register("name")} /></Field>
            <Field label="Channel" htmlFor="nt-channel">
              <Select value={channel} disabled={Boolean(editing)} onValueChange={(v) => form.setValue("channel", v as "email" | "telegram")}>
                <SelectTrigger id="nt-channel"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="email">Email</SelectItem><SelectItem value="telegram">Telegram</SelectItem></SelectContent>
              </Select>
            </Field>
            {channel === "email" && <Field label="Email address" htmlFor="nt-address" error={form.formState.errors.address?.message}><Input id="nt-address" type="email" {...form.register("address")} /></Field>}
            <div className="flex items-center gap-2"><Switch id="nt-enabled" checked={form.watch("enabled")} onCheckedChange={(v) => form.setValue("enabled", v)} /><label htmlFor="nt-enabled" className="text-sm">Enabled</label></div>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" disabled={save.isPending}>Save</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={linking !== null} onOpenChange={(o) => !o && setLinking(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Link a Telegram chat</DialogTitle><DialogDescription>From the chat or group that should receive alerts, send this command to the bot. The code is valid until {formatTime(linking?.telegram_link_expires_at)}.</DialogDescription></DialogHeader>
          {linking && (
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2"><code className="flex-1 rounded bg-muted p-2">/start {linking.telegram_link_code}</code><Button variant="outline" size="icon" aria-label="Copy command" onClick={() => { void navigator.clipboard.writeText(`/start ${linking.telegram_link_code}`); toast.success("Copied"); }}><Copy className="size-4" /></Button></div>
              {linking.link_url ? <div>Or open <a className="underline" href={linking.link_url} target="_blank" rel="noreferrer">{linking.link_url}</a> on a phone with Telegram.</div> : <div className="text-muted-foreground">The bot username is not known to the server yet; find the bot by the name it was created with.</div>}
              <div className="text-muted-foreground">The automation service links the chat within a few seconds; the target then shows as linked. Use Test to confirm.</div>
            </div>
          )}
          <DialogFooter><Button onClick={() => setLinking(null)}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete target ${removing?.name ?? ""}?`} description="Automations that use it will fail their notify action until they are edited." confirmLabel="Delete" pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </>
  );
}

export function AdminNotificationsPage() {
  return <NotificationsPage scope="server" />;
}
