import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Entity, Feature, Metric, Page as PageType, ReplayResult, Rule, RuleTemplate, RuleVersion } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { JsonView } from "@/components/common/JsonView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { DataTable } from "@/components/data/DataTable";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";
import { AGGREGATES, CONDITION_TYPES, DERIVED_METRICS, defaultForm, documentToForm, emptyCondition, FEATURE_TYPES, formToDocument, OPERATORS, RELATIONS, type RuleFormValues, SEVERITIES, TRIGGER_KINDS } from "@/lib/rules";

const conditionSchema = z.object({
  type: z.string(),
  metric: z.string(),
  op: z.string(),
  value: z.number(),
  relation: z.string(),
  feature_type: z.string(),
  feature_ids: z.array(z.string()),
  for_seconds: z.number().int().min(60),
  aggregate: z.string(),
  seconds: z.number().int().min(60),
});
const schema = z.object({
  name: z.string().min(1).max(200),
  description: z.string(),
  trigger_kind: z.string(),
  metric_key: z.string(),
  every_seconds: z.number().int().min(60).max(86400),
  entity_ids: z.array(z.string()),
  conditions: z.array(conditionSchema).min(1, "Add at least one condition"),
  for_seconds: z.number().int().min(0),
  cooldown_seconds: z.number().int().min(0),
  event_type: z.string().regex(/^[A-Z][A-Z0-9_]{1,63}$/, "Upper case letters, digits and underscores, for example GEOFENCE_EXIT"),
  severity: z.string(),
  title: z.string().min(1).max(300),
  event_description: z.string(),
  create_alert: z.boolean(),
});
type Values = z.infer<typeof schema>;

const NUMBER = "h-8 w-24";

function toForm(rule: Rule | null, template: RuleTemplate | null): { values: Values; json: string | null } {
  const doc = rule?.document ?? template?.document ?? null;
  const base = doc ? documentToForm(doc as Record<string, unknown>) : defaultForm();
  const name = rule?.name ?? template?.name ?? "";
  const description = rule?.description ?? template?.description ?? "";
  if (!base) return { values: { ...flatten(defaultForm()), name, description }, json: JSON.stringify(doc, null, 2) };
  return { values: { ...flatten(base), name, description }, json: null };
}

function flatten(v: RuleFormValues): Omit<Values, "name" | "description"> {
  const { description, ...rest } = v;
  return { ...rest, event_description: description };
}

function unflatten(v: Values): RuleFormValues {
  return {
    trigger_kind: v.trigger_kind,
    metric_key: v.metric_key,
    every_seconds: v.every_seconds,
    entity_ids: v.entity_ids,
    conditions: v.conditions,
    for_seconds: v.for_seconds,
    cooldown_seconds: v.cooldown_seconds,
    event_type: v.event_type,
    severity: v.severity,
    title: v.title,
    description: v.event_description,
    create_alert: v.create_alert,
  };
}

interface Props {
  projectId: string;
  rule: Rule | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Create or edit a rule (architecture 15, decision D9). The form covers one leaf or an `all`
 * of leaves; documents with nesting the form cannot show are edited as JSON. Editing an
 * existing rule saves a new version; name, description and enabled are patched separately.
 */
export function RuleEditor({ projectId, rule, open, onOpenChange }: Props) {
  const base = `/api/v1/projects/${projectId}/rules`;
  const templates = useQuery({ queryKey: queryKeys.ruleTemplates(projectId), queryFn: () => api.get<RuleTemplate[]>(`${base}/templates`), enabled: open });
  const entities = useQuery({ queryKey: queryKeys.entities(projectId), queryFn: () => api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, { query: { limit: 500 } }), enabled: open });
  const features = useQuery({ queryKey: queryKeys.features(projectId), queryFn: () => api.get<PageType<Feature>>(`/api/v1/projects/${projectId}/features`, { query: { limit: 500 } }), enabled: open });
  const metrics = useQuery({ queryKey: queryKeys.metrics, queryFn: () => api.get<PageType<Metric>>("/api/v1/metrics", { query: { limit: 500 } }), enabled: open });
  const versions = useQuery({ queryKey: queryKeys.ruleVersions(projectId, rule?.id ?? ""), queryFn: () => api.get<RuleVersion[]>(`${base}/${rule?.id}/versions`), enabled: open && Boolean(rule) });
  const [template, setTemplate] = useState<string>("");
  const [json, setJson] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [range, setRange] = useState(() => ({ from: new Date(Date.now() - 7 * 86400_000).toISOString().slice(0, 16), to: new Date().toISOString().slice(0, 16) }));
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { ...flatten(defaultForm()), name: "", description: "" } });
  const conditions = useFieldArray({ control: form.control, name: "conditions" });

  useEffect(() => {
    if (!open) return;
    const chosen = templates.data?.find((t) => t.key === template) ?? null;
    const { values, json: rawJson } = toForm(rule, rule ? null : chosen);
    form.reset(values);
    setJson(rawJson);
    setJsonError(null);
    setReplay(null);
  }, [open, rule, template, templates.data, form]);

  const metricOptions = [...DERIVED_METRICS, ...(metrics.data?.items.map((m) => m.key) ?? [])];
  const invalidate = [queryKeys.rules(projectId), queryKeys.ruleVersions(projectId, rule?.id ?? "")];

  function buildDocument(values: Values): Record<string, unknown> | null {
    if (json !== null) {
      try {
        const parsed = JSON.parse(json) as unknown;
        if (!parsed || typeof parsed !== "object") throw new Error("not an object");
        setJsonError(null);
        return parsed as Record<string, unknown>;
      } catch (e) {
        setJsonError(`Invalid JSON: ${(e as Error).message}`);
        return null;
      }
    }
    return formToDocument(unflatten(values));
  }

  const save = useMutationToast({
    mutationFn: async (values: Values) => {
      const document = buildDocument(values);
      if (!document) throw new Error("Fix the JSON first");
      if (!rule) return api.post<Rule>(base, { body: { name: values.name, description: values.description || null, document, enabled: false } });
      await api.patch<Rule>(`${base}/${rule.id}`, { body: { name: values.name, description: values.description || null } });
      return api.put<Rule>(`${base}/${rule.id}/document`, { body: { document } });
    },
    invalidate,
    success: rule ? "New rule version saved" : "Rule created (disabled until you enable it)",
    onSuccess: () => onOpenChange(false),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const test = useMutationToast({
    mutationFn: async (values: Values) => {
      const document = buildDocument(values);
      if (!document) throw new Error("Fix the JSON first");
      const body = { from: new Date(range.from).toISOString(), to: new Date(range.to).toISOString(), document };
      return api.post<ReplayResult>(`${base}/test-document`, { body });
    },
    onSuccess: (result) => setReplay(result),
    onError: (error) => form.setError("root", { message: error.message }),
  });

  const kind = form.watch("trigger_kind");
  const err = form.formState.errors;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{rule ? `Edit rule: ${rule.name}` : "New rule"}</DialogTitle>
          <DialogDescription>{rule ? `Version ${rule.current_version}. Saving creates a new version; events keep the version that created them.` : "Start from a template or build the rule from scratch. New rules start disabled."}</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="definition">
          <TabsList>
            <TabsTrigger value="definition">Definition</TabsTrigger>
            <TabsTrigger value="test">Test on history</TabsTrigger>
            {rule && <TabsTrigger value="versions">Versions</TabsTrigger>}
          </TabsList>
          <TabsContent value="definition">
            <form id="rule-form" className="space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
              {!rule && (
                <Field label="Template" htmlFor="rule-template" hint="Optional starting point; every field stays editable">
                  <Select value={template || "none"} onValueChange={(v) => setTemplate(v === "none" ? "" : v)}>
                    <SelectTrigger id="rule-template"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="none">From scratch</SelectItem>{templates.data?.map((t) => <SelectItem key={t.key} value={t.key}>{t.name}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Name" htmlFor="rule-name" error={err.name?.message}><Input id="rule-name" {...form.register("name")} /></Field>
                <Field label="Description" htmlFor="rule-description"><Input id="rule-description" {...form.register("description")} /></Field>
              </div>
              {json !== null ? (
                <Field label="Document (JSON)" htmlFor="rule-json" hint="This document uses nesting the form cannot show, so it is edited as JSON" error={jsonError ?? undefined}>
                  <Textarea id="rule-json" rows={18} className="font-mono text-xs" value={json} onChange={(e) => setJson(e.target.value)} />
                </Field>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Trigger" htmlFor="rule-trigger">
                      <Select value={kind} onValueChange={(v) => form.setValue("trigger_kind", v)}>
                        <SelectTrigger id="rule-trigger"><SelectValue /></SelectTrigger>
                        <SelectContent>{TRIGGER_KINDS.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
                      </Select>
                    </Field>
                    {kind === "measurement" && (
                      <Field label="Metric" htmlFor="rule-metric" hint="Empty means any metric">
                        <Input id="rule-metric" list="metric-keys" {...form.register("metric_key")} />
                      </Field>
                    )}
                    {kind === "schedule" && (
                      <Field label="Check every (seconds)" htmlFor="rule-every" error={err.every_seconds?.message}><Input id="rule-every" type="number" {...form.register("every_seconds", { valueAsNumber: true })} /></Field>
                    )}
                    <Field label="Entities" htmlFor="rule-scope" hint="Empty means every entity of the project">
                      <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto">
                        {entities.data?.items.map((e) => { const on = form.watch("entity_ids").includes(e.id); return <Button key={e.id} type="button" size="sm" variant={on ? "default" : "outline"} className="h-7" onClick={() => form.setValue("entity_ids", on ? form.getValues("entity_ids").filter((x) => x !== e.id) : [...form.getValues("entity_ids"), e.id])}>{e.name}</Button>; })}
                      </div>
                    </Field>
                  </div>
                  <datalist id="metric-keys">{metricOptions.map((m) => <option key={m} value={m} />)}</datalist>
                  <div className="space-y-2 rounded-md border p-3">
                    <div className="flex items-center justify-between"><span className="text-sm font-medium">Conditions (all must hold)</span><Button type="button" size="sm" variant="outline" onClick={() => conditions.append(emptyCondition())}><Plus className="size-4" /> Add condition</Button></div>
                    {typeof err.conditions?.message === "string" && <p className="text-sm text-destructive">{err.conditions.message}</p>}
                    {conditions.fields.map((field, index) => {
                      const type = form.watch(`conditions.${index}.type`);
                      return (
                        <div key={field.id} className="flex flex-wrap items-end gap-2 rounded bg-muted/40 p-2">
                          <Select value={type} onValueChange={(v) => form.setValue(`conditions.${index}`, { ...emptyCondition(v), ...(v === "threshold" || v === "window" ? { metric: form.getValues(`conditions.${index}.metric`) } : {}) })}>
                            <SelectTrigger className="h-8 w-44" aria-label="Condition type"><SelectValue /></SelectTrigger>
                            <SelectContent>{CONDITION_TYPES.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
                          </Select>
                          {(type === "threshold" || type === "window") && <Input className="h-8 w-40" list="metric-keys" aria-label="Metric" {...form.register(`conditions.${index}.metric`)} />}
                          {type === "window" && (
                            <>
                              <Select value={form.watch(`conditions.${index}.aggregate`)} onValueChange={(v) => form.setValue(`conditions.${index}.aggregate`, v)}>
                                <SelectTrigger className="h-8 w-24" aria-label="Aggregate"><SelectValue /></SelectTrigger>
                                <SelectContent>{AGGREGATES.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}</SelectContent>
                              </Select>
                              <span className="text-xs text-muted-foreground">over</span>
                              <Input className={NUMBER} type="number" aria-label="Window seconds" {...form.register(`conditions.${index}.seconds`, { valueAsNumber: true })} />
                              <span className="text-xs text-muted-foreground">s</span>
                            </>
                          )}
                          {(type === "threshold" || type === "window") && (
                            <>
                              <Select value={form.watch(`conditions.${index}.op`)} onValueChange={(v) => form.setValue(`conditions.${index}.op`, v)}>
                                <SelectTrigger className="h-8 w-16" aria-label="Operator"><SelectValue /></SelectTrigger>
                                <SelectContent>{OPERATORS.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                              </Select>
                              <Input className={NUMBER} type="number" step="any" aria-label="Value" {...form.register(`conditions.${index}.value`, { valueAsNumber: true })} />
                            </>
                          )}
                          {type === "spatial" && (
                            <>
                              <Select value={form.watch(`conditions.${index}.relation`)} onValueChange={(v) => form.setValue(`conditions.${index}.relation`, v)}>
                                <SelectTrigger className="h-8 w-28" aria-label="Relation"><SelectValue /></SelectTrigger>
                                <SelectContent>{RELATIONS.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                              </Select>
                              <Select value={form.watch(`conditions.${index}.feature_ids`).length > 0 ? "selected" : form.watch(`conditions.${index}.feature_type`)} onValueChange={(v) => { if (v === "selected") return; form.setValue(`conditions.${index}.feature_type`, v); form.setValue(`conditions.${index}.feature_ids`, []); }}>
                                <SelectTrigger className="h-8 w-36" aria-label="Feature type"><SelectValue /></SelectTrigger>
                                <SelectContent>{FEATURE_TYPES.map((f) => <SelectItem key={f} value={f}>every {f}</SelectItem>)}<SelectItem value="selected" disabled>selected features</SelectItem></SelectContent>
                              </Select>
                              <div className="flex flex-wrap gap-1">
                                {features.data?.items.map((f) => { const on = form.watch(`conditions.${index}.feature_ids`).includes(f.id); return <Button key={f.id} type="button" size="sm" variant={on ? "default" : "outline"} className="h-7" onClick={() => { const current = form.getValues(`conditions.${index}.feature_ids`); form.setValue(`conditions.${index}.feature_ids`, on ? current.filter((x) => x !== f.id) : [...current, f.id]); }}>{f.name}</Button>; })}
                              </div>
                            </>
                          )}
                          {type === "no_data" && (
                            <>
                              <span className="text-xs text-muted-foreground">for</span>
                              <Input className={NUMBER} type="number" aria-label="Silence seconds" {...form.register(`conditions.${index}.for_seconds`, { valueAsNumber: true })} />
                              <span className="text-xs text-muted-foreground">seconds</span>
                            </>
                          )}
                          <Button type="button" size="icon" variant="ghost" className="ml-auto size-8" aria-label="Remove condition" onClick={() => conditions.remove(index)}><Trash2 className="size-4" /></Button>
                        </div>
                      );
                    })}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Must hold for (seconds)" htmlFor="rule-for" hint="0 fires as soon as the condition is true" error={err.for_seconds?.message}><Input id="rule-for" type="number" {...form.register("for_seconds", { valueAsNumber: true })} /></Field>
                    <Field label="Cooldown (seconds)" htmlFor="rule-cooldown" hint="While the condition stays true, remind again after this long; 0 never" error={err.cooldown_seconds?.message}><Input id="rule-cooldown" type="number" {...form.register("cooldown_seconds", { valueAsNumber: true })} /></Field>
                  </div>
                  <div className="space-y-3 rounded-md border p-3">
                    <span className="text-sm font-medium">Event</span>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Field label="Event type" htmlFor="rule-event-type" error={err.event_type?.message}><Input id="rule-event-type" placeholder="GEOFENCE_EXIT" {...form.register("event_type")} /></Field>
                      <Field label="Severity" htmlFor="rule-severity">
                        <Select value={form.watch("severity")} onValueChange={(v) => form.setValue("severity", v)}>
                          <SelectTrigger id="rule-severity"><SelectValue /></SelectTrigger>
                          <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                        </Select>
                      </Field>
                      <div className="flex items-end gap-2 pb-2"><Switch id="rule-alert" checked={form.watch("create_alert")} onCheckedChange={(v) => form.setValue("create_alert", v)} /><label htmlFor="rule-alert" className="text-sm">Create an alert</label></div>
                    </div>
                    <Field label="Title" htmlFor="rule-title" hint="Placeholders: {entity} {device} {feature} {metric} {value} {rule}" error={err.title?.message}><Input id="rule-title" {...form.register("title")} /></Field>
                    <Field label="Description" htmlFor="rule-event-description"><Textarea id="rule-event-description" rows={2} {...form.register("event_description")} /></Field>
                  </div>
                </>
              )}
              {err.root && <Callout kind="error">{err.root.message}</Callout>}
            </form>
          </TabsContent>
          <TabsContent value="test">
            <div className="space-y-3">
              <Callout kind="info">Replays the definition above over the project's positions and measurements without creating anything. Bounded to 50,000 rows and 500 events.</Callout>
              <div className="flex flex-wrap items-end gap-2">
                <Field label="From" htmlFor="replay-from"><Input id="replay-from" type="datetime-local" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
                <Field label="To" htmlFor="replay-to"><Input id="replay-to" type="datetime-local" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
                <Button type="button" onClick={() => void form.handleSubmit((v: Values) => test.mutate(v))()} disabled={test.isPending}>{test.isPending ? "Running…" : "Run test"}</Button>
              </div>
              {replay && (
                <>
                  <div className="text-sm text-muted-foreground">{replay.total} events over {replay.samples} samples{replay.truncated ? ", showing the first 500" : ""}</div>
                  <DataTable columns={[{ header: "Time", accessorKey: "time", cell: ({ getValue }) => formatTime(getValue<string>()) }, { header: "Subject", accessorKey: "subject_key" }, { header: "Title", accessorKey: "title" }, { header: "Reason", accessorKey: "reason" }]} data={replay.events} emptyMessage="The rule would not have fired in this range." />
                </>
              )}
            </div>
          </TabsContent>
          {rule && (
            <TabsContent value="versions">
              <div className="space-y-2">
                {versions.data?.map((v) => (
                  <details key={v.id} className="rounded-md border p-2" open={v.version === rule.current_version}>
                    <summary className="cursor-pointer text-sm">Version {v.version} <span className="text-muted-foreground">{formatTime(v.created_at)}</span> {v.version === rule.current_version && <StatusBadge value="active" />}</summary>
                    <div className="mt-2"><JsonView value={v.document} /></div>
                  </details>
                ))}
              </div>
            </TabsContent>
          )}
        </Tabs>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="rule-form" disabled={save.isPending}>{rule ? "Save new version" : "Create rule"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
