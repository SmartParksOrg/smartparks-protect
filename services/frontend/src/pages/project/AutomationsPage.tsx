import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useParams, useSearchParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Automation, Delivery, NotificationTarget, Page as PageType } from "@/api/types";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import { type Scope, scopeBase, SEVERITIES } from "@/lib/rules";

const actionSchema = z.object({ type: z.enum(["notify", "webhook", "command"]), target_id: z.string(), url: z.string(), secret: z.string(), action_key: z.string(), parameters: z.string() })
  .refine((a) => a.type !== "notify" || a.target_id, { path: ["target_id"], message: "Choose a target" })
  .refine((a) => a.type !== "webhook" || /^https?:\/\//.test(a.url), { path: ["url"], message: "An http(s) URL is needed" })
  .refine((a) => a.type !== "command" || /^[A-Z][A-Z0-9_]+$/.test(a.action_key), { path: ["action_key"], message: "An action key like REQUEST_STATUS is needed" })
  .refine((a) => { if (a.type !== "command" || !a.parameters.trim()) return true; try { return typeof JSON.parse(a.parameters) === "object"; } catch { return false; } }, { path: ["parameters"], message: "Parameters must be a JSON object" });
const schema = z.object({
  name: z.string().min(1).max(200),
  description: z.string(),
  enabled: z.boolean(),
  event_types: z.string(),
  min_severity: z.enum(["info", "warning", "critical"]),
  require_alert: z.boolean(),
  max_event_age_hours: z.number().min(0.1).max(720),
  actions: z.array(actionSchema).min(1, "Add at least one action"),
});
type Values = z.infer<typeof schema>;

function toValues(a: Automation | null): Values {
  return a
    ? { name: a.name, description: a.description ?? "", enabled: a.enabled, event_types: a.event_types.join(", "), min_severity: a.min_severity as Values["min_severity"], require_alert: a.require_alert, max_event_age_hours: a.max_event_age_seconds / 3600, actions: a.actions.map((x) => ({ type: (x.type as "notify" | "webhook" | "command") ?? "notify", target_id: String(x.target_id ?? ""), url: String(x.url ?? ""), secret: String(x.secret ?? ""), action_key: String(x.action_key ?? ""), parameters: x.parameters ? JSON.stringify(x.parameters) : "" })) }
    : { name: "", description: "", enabled: true, event_types: "", min_severity: "warning", require_alert: false, max_event_age_hours: 6, actions: [{ type: "notify", target_id: "", url: "", secret: "", action_key: "", parameters: "" }] };
}

function toBody(v: Values) {
  return {
    name: v.name,
    description: v.description || null,
    enabled: v.enabled,
    event_types: v.event_types.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
    min_severity: v.min_severity,
    require_alert: v.require_alert,
    max_event_age_seconds: Math.round(v.max_event_age_hours * 3600),
    actions: v.actions.map((a) => (a.type === "notify" ? { type: "notify", target_id: a.target_id } : a.type === "command" ? { type: "command", action_key: a.action_key, parameters: a.parameters.trim() ? (JSON.parse(a.parameters) as Record<string, unknown>) : {} } : { type: "webhook", url: a.url, ...(a.secret ? { secret: a.secret } : {}) })),
  };
}

/** Automations bind events to actions (architecture 16); deliveries show what each action did. */
export function AutomationsPage({ scope: scopeProp }: { scope?: Scope } = {}) {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const scope = scopeProp ?? projectId;
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "deliveries" ? "deliveries" : "automations";
  const base = scopeBase(scope);
  const automations = useQuery({ queryKey: queryKeys.automations(scope), queryFn: () => api.get<PageType<Automation>>(`${base}/automations`, { query: { limit: 500 } }) });
  const targets = useQuery({ queryKey: queryKeys.notificationTargets(scope), queryFn: () => api.get<PageType<NotificationTarget>>(`${base}/notification-targets`, { query: { limit: 500 } }) });
  const deliveryStatus = params.get("status") ?? "";
  const deliveries = useQuery({ queryKey: queryKeys.deliveries(scope, { status: deliveryStatus }), queryFn: () => api.get<PageType<Delivery>>(`${base}/deliveries`, { query: { limit: 200, status: deliveryStatus || undefined } }), enabled: tab === "deliveries", refetchInterval: tab === "deliveries" ? 15_000 : false });
  const [editing, setEditing] = useState<Automation | null>(null);
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState<Automation | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(null) });
  const actions = useFieldArray({ control: form.control, name: "actions" });
  useEffect(() => { if (open) form.reset(toValues(editing)); }, [open, editing, form]);
  const invalidate = [queryKeys.automations(scope)];
  const save = useMutationToast({
    mutationFn: (v: Values) => (editing ? api.patch<Automation>(`${base}/automations/${editing.id}`, { body: toBody(v) }) : api.post<Automation>(`${base}/automations`, { body: toBody(v) })),
    invalidate,
    success: editing ? "Automation saved" : "Automation created",
    onSuccess: () => setOpen(false),
    onError: (e) => form.setError("root", { message: e.message }),
  });
  const toggle = useMutationToast({ mutationFn: ({ a, enabled }: { a: Automation; enabled: boolean }) => api.patch<Automation>(`${base}/automations/${a.id}`, { body: { enabled } }), invalidate, success: (a) => (a.enabled ? "Automation enabled" : "Automation disabled") });
  const remove = useMutationToast({ mutationFn: (a: Automation) => api.delete<void>(`${base}/automations/${a.id}`), invalidate, success: t("Automation deleted"), onSuccess: () => setRemoving(null) });
  const retry = useMutationToast({ mutationFn: (d: Delivery) => api.post<Delivery>(`${base}/deliveries/${d.id}/retry`), invalidate: [queryKeys.deliveries(scope, { status: deliveryStatus })], success: t("Queued again") });
  const targetName = (id: string | null | undefined) => targets.data?.items.find((t) => t.id === id)?.name ?? "target";
  const automationName = (id: string | null) => automations.data?.items.find((a) => a.id === id)?.name ?? "";

  const columns: ColumnDef<Automation, unknown>[] = [
    { header: t("Enabled"), accessorKey: "enabled", cell: ({ row }) => <span onClick={(e) => e.stopPropagation()}><Switch checked={row.original.enabled} aria-label={`Enable ${row.original.name}`} onCheckedChange={(v) => toggle.mutate({ a: row.original, enabled: v })} /></span> },
    { header: t("Name"), accessorKey: "name" },
    { header: t("Events"), id: "events", cell: ({ row }) => <span className="text-xs">{row.original.event_types.length ? row.original.event_types.join(", ") : "any type"}, {row.original.min_severity} {t("and up")}{row.original.require_alert ? ", alerts only" : ""}</span> },
    { header: t("Actions"), id: "actions", cell: ({ row }) => <span className="text-xs">{row.original.actions.map((a, i) => <span key={i} className="mr-2">{a.type === "notify" ? `notify ${targetName(String(a.target_id))}` : a.type === "command" ? `command ${String(a.action_key ?? "")}` : `webhook ${String(a.url ?? "")}`}</span>)}</span> },
    { header: t("Max age"), accessorKey: "max_event_age_seconds", cell: ({ getValue }) => `${getValue<number>() / 3600} h` },
    { id: "remove", header: "", cell: ({ row }) => <span onClick={(e) => e.stopPropagation()}><Button variant="ghost" size="icon" aria-label={t("Delete automation")} onClick={() => setRemoving(row.original)}><Trash2 className="size-4" /></Button></span> },
  ];
  const deliveryColumns: ColumnDef<Delivery, unknown>[] = [
    { header: t("Created"), accessorKey: "created_at", cell: ({ getValue }) => formatTime(getValue<string>()) },
    { header: t("Automation"), accessorKey: "automation_id", cell: ({ getValue }) => automationName(getValue<string | null>()) },
    { header: t("Action"), accessorKey: "action_type", cell: ({ row }) => row.original.action_type === "notify" ? `notify ${targetName(row.original.target_id)}` : row.original.action_type },
    { header: t("Status"), accessorKey: "status", cell: ({ row }) => <span className="inline-flex items-center gap-2"><StatusBadge value={row.original.status} /><span className="text-xs text-muted-foreground">{row.original.attempts} {t("attempt")}{row.original.attempts === 1 ? "" : "s"}</span></span> },
    { header: t("Detail"), accessorKey: "error_message", cell: ({ getValue }) => <span className="text-xs">{getValue<string | null>() ?? ""}</span> },
    { id: "retry", header: "", cell: ({ row }) => row.original.status === "failed" && <Button variant="ghost" size="sm" onClick={() => retry.mutate(row.original)}><RotateCcw className="size-4" /> {t("Retry")}</Button> },
  ];

  return (
    <>
      <PageHeader title={t("Automations")} description={scope === "server" ? "What happens with system alerts: notify server-level targets or call a webhook" : "What happens when an event occurs: notify a target or call a webhook, with a freshness bound so old data never pages anyone"} actions={<Button onClick={() => { setEditing(null); setOpen(true); }}><Plus className="size-4" /> {t("New automation")}</Button>} />
      <Page>
        <div className="flex flex-wrap items-center gap-3">
          <Tabs value={tab} onValueChange={(v) => setParams((p) => { p.set("tab", v); return p; }, { replace: true })}><TabsList><TabsTrigger value="automations">{t("Automations")}</TabsTrigger><TabsTrigger value="deliveries">{t("Deliveries")}</TabsTrigger></TabsList></Tabs>
          {tab === "deliveries" && (
            <Select value={deliveryStatus || "all"} onValueChange={(v) => setParams((p) => { if (v === "all") p.delete("status"); else p.set("status", v); return p; }, { replace: true })}>
              <SelectTrigger className="w-36" aria-label={t("Delivery status")}><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">{t("Any status")}</SelectItem>{["queued", "sent", "failed", "skipped"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
          )}
        </div>
        {(automations.error ?? deliveries.error) && <Callout kind="error">{(automations.error ?? deliveries.error)?.message}</Callout>}
        {tab === "automations" ? (
          <DataTable columns={columns} data={automations.data?.items} searchable isLoading={automations.isPending} emptyMessage={t("No automations yet. Create a notification target first, then bind events to it here.")} onRowClick={(a) => { setEditing(a); setOpen(true); }} />
        ) : (
          <DataTable columns={deliveryColumns} data={deliveries.data?.items} searchable isLoading={deliveries.isPending} emptyMessage={t("No deliveries yet.")} footer={deliveries.data && `${deliveries.data.items.length} deliveries`} />
        )}
      </Page>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader><DialogTitle>{editing ? "Edit automation" : "New automation"}</DialogTitle><DialogDescription>{t("Events older than the freshness bound are skipped, so a log upload of last month never sends today's alerts.")}</DialogDescription></DialogHeader>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <Field label={t("Name")} htmlFor="au-name" error={form.formState.errors.name?.message}><Input id="au-name" {...form.register("name")} /></Field>
            <Field label={t("Description")} htmlFor="au-description"><Input id="au-description" {...form.register("description")} /></Field>
            <Field label={t("Event types")} htmlFor="au-types" hint={t("Comma separated; empty means every type")}><Input id="au-types" placeholder={t("GEOFENCE_EXIT, BATTERY_LOW")} {...form.register("event_types")} /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Minimum severity")} htmlFor="au-severity">
                <Select value={form.watch("min_severity")} onValueChange={(v) => form.setValue("min_severity", v as Values["min_severity"])}>
                  <SelectTrigger id="au-severity"><SelectValue /></SelectTrigger>
                  <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label={t("Skip events older than (hours)")} htmlFor="au-age" error={form.formState.errors.max_event_age_hours?.message}><Input id="au-age" type="number" step="any" {...form.register("max_event_age_hours", { valueAsNumber: true })} /></Field>
            </div>
            <div className="flex flex-wrap gap-4">
              <span className="flex items-center gap-2"><Switch id="au-alert" checked={form.watch("require_alert")} onCheckedChange={(v) => form.setValue("require_alert", v)} /><label htmlFor="au-alert" className="text-sm">{t("Only events with an alert")}</label></span>
              <span className="flex items-center gap-2"><Switch id="au-enabled" checked={form.watch("enabled")} onCheckedChange={(v) => form.setValue("enabled", v)} /><label htmlFor="au-enabled" className="text-sm">{t("Enabled")}</label></span>
            </div>
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center justify-between"><span className="text-sm font-medium">{t("Actions")}</span><Button type="button" size="sm" variant="outline" onClick={() => actions.append({ type: "notify", target_id: "", url: "", secret: "", action_key: "", parameters: "" })}><Plus className="size-4" /> {t("Add action")}</Button></div>
              {typeof form.formState.errors.actions?.message === "string" && <p className="text-sm text-destructive">{form.formState.errors.actions.message}</p>}
              {actions.fields.map((field, index) => {
                const type = form.watch(`actions.${index}.type`);
                const errs = form.formState.errors.actions?.[index];
                return (
                  <div key={field.id} className="flex flex-wrap items-start gap-2 rounded bg-muted/40 p-2">
                    <Select value={type} onValueChange={(v) => form.setValue(`actions.${index}.type`, v as "notify" | "webhook" | "command")}>
                      <SelectTrigger className="h-8 w-28" aria-label={t("Action type")}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="notify">{t("Notify")}</SelectItem><SelectItem value="webhook">{t("Webhook")}</SelectItem><SelectItem value="command">{t("Device command")}</SelectItem></SelectContent>
                    </Select>
                    {type === "notify" ? (
                      <div className="min-w-48 flex-1">
                        <Select value={form.watch(`actions.${index}.target_id`) || "none"} onValueChange={(v) => form.setValue(`actions.${index}.target_id`, v === "none" ? "" : v)}>
                          <SelectTrigger className="h-8" aria-label={t("Target")}><SelectValue placeholder={t("Choose a target")} /></SelectTrigger>
                          <SelectContent><SelectItem value="none" disabled>{t("Choose a target")}</SelectItem>{targets.data?.items.map((t) => <SelectItem key={t.id} value={t.id}>{t.name} ({t.channel})</SelectItem>)}</SelectContent>
                        </Select>
                        {errs?.target_id && <p className="text-xs text-destructive">{errs.target_id.message}</p>}
                      </div>
                    ) : type === "command" ? (
                      <div className="flex min-w-48 flex-1 flex-col gap-1">
                        <Input className="h-8" placeholder={t("REQUEST_STATUS")} aria-label={t("Action key")} {...form.register(`actions.${index}.action_key`)} />
                        <Input className="h-8 font-mono text-xs" placeholder={t("{\"interval_seconds\": 600} (optional)")} aria-label={t("Parameters JSON")} {...form.register(`actions.${index}.parameters`)} />
                        <p className="text-xs text-muted-foreground">{t("Sent to the event's device through the same path as the Actions menu.")}</p>
                        {errs?.action_key && <p className="text-xs text-destructive">{errs.action_key.message}</p>}
                        {errs?.parameters && <p className="text-xs text-destructive">{errs.parameters.message}</p>}
                      </div>
                    ) : (
                      <div className="flex min-w-48 flex-1 flex-col gap-1">
                        <Input className="h-8" placeholder={t("https://…")} aria-label={t("Webhook URL")} {...form.register(`actions.${index}.url`)} />
                        <Input className="h-8" placeholder={t("Signing secret (optional)")} aria-label={t("Webhook secret")} {...form.register(`actions.${index}.secret`)} />
                        {errs?.url && <p className="text-xs text-destructive">{errs.url.message}</p>}
                      </div>
                    )}
                    <Button type="button" size="icon" variant="ghost" className="size-8" aria-label={t("Remove action")} onClick={() => actions.remove(index)}><Trash2 className="size-4" /></Button>
                  </div>
                );
              })}
            </div>
            {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
            <DialogFooter><Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending}>{t("Save")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete automation ${removing?.name ?? ""}?`} description={t("Past deliveries stay in the log.")} confirmLabel={t("Delete")} pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </>
  );
}

export function AdminAutomationsPage() {
  return <AutomationsPage scope="server" />;
}
