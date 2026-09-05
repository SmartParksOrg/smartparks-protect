import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DataSource, ProjectWithRole } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";

export interface AdapterChannel { key: string; label: string; direction: string; purpose: string; hint?: string | null; config_keys: string[]; optional_keys?: string[]; credential_keys: string[]; optional_credential_keys?: string[]; capabilities?: string[] }
export interface SchemaProperty { type?: string; description?: string; default?: unknown; enum?: unknown[]; items?: { type?: string }; minimum?: number; maximum?: number }
export interface AdapterInfo {
  key: string;
  label: string;
  push: boolean;
  can_send_commands: boolean;
  can_manage: boolean;
  polling: boolean;
  builtin: boolean;
  webhook_token_in_query: boolean;
  config_schema: { required?: string[]; properties?: Record<string, SchemaProperty> };
  config_example: Record<string, unknown>;
  credentials_schema: Record<string, string>;
  setup_hint: string;
  default_capabilities: Record<string, boolean>;
  channels: AdapterChannel[];
}

type Values = Record<string, unknown>;

const isFilled = (v: unknown) => v !== undefined && v !== null && String(v).trim() !== "";

/** Initial values for a new source: the schema's defaults under the adapter's example. */
function initialConfig(adapter: AdapterInfo | undefined): Values {
  if (!adapter) return {};
  const values: Values = {};
  for (const [key, prop] of Object.entries(adapter.config_schema.properties ?? {})) if (prop.default !== undefined) values[key] = prop.default;
  return { ...values, ...adapter.config_example };
}

function defaultSwitches(adapter: AdapterInfo | undefined): Record<string, boolean> {
  const example = initialConfig(adapter);
  return Object.fromEntries((adapter?.channels ?? []).map((c) => [c.key, c.config_keys.every((k) => isFilled(example[k])) && c.credential_keys.length === 0]));
}

/** One control per schema property: switch, number, select, list, or text. */
function PropertyField({ id, name, prop, required, value, onChange }: { id: string; name: string; prop: SchemaProperty; required: boolean; value: unknown; onChange: (v: unknown) => void }) {
  const { t } = useTranslation();
  const label = required ? `${name} *` : name;
  const hint = prop.description ?? undefined;
  if (prop.type === "boolean") {
    return <div className="flex items-start gap-2"><Switch id={id} checked={Boolean(value)} onCheckedChange={(v) => onChange(v)} /><label htmlFor={id} className="text-sm">{name}{hint && <span className="block text-xs text-muted-foreground">{hint}</span>}</label></div>;
  }
  if (prop.enum) {
    return <Field label={label} htmlFor={id} hint={hint}><Select value={value === undefined || value === null || value === "" ? "__none" : String(value)} onValueChange={(v) => onChange(v === "__none" ? "" : v)}><SelectTrigger id={id}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none">{t("(not set)")}</SelectItem>{prop.enum.map((o) => <SelectItem key={String(o)} value={String(o)}>{String(o)}</SelectItem>)}</SelectContent></Select></Field>;
  }
  if (prop.type === "integer" || prop.type === "number") {
    return <Field label={label} htmlFor={id} hint={hint}><Input id={id} type="number" step={prop.type === "integer" ? 1 : "any"} min={prop.minimum} max={prop.maximum} value={value === undefined || value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} /></Field>;
  }
  if (prop.type === "array") {
    const list = Array.isArray(value) ? value : [];
    return <Field label={label} htmlFor={id} hint={[hint, t("Comma separated")].filter(Boolean).join(". ")}><Input id={id} value={list.map(String).join(", ")} onChange={(e) => { const parts = e.target.value.split(",").map((p) => p.trim()).filter(Boolean); onChange(prop.items?.type === "integer" || prop.items?.type === "number" ? parts.map(Number).filter((n) => !Number.isNaN(n)) : parts); }} /></Field>;
  }
  if (prop.type === "object") {
    return <Field label={label} htmlFor={id} hint={[hint, t("JSON")].filter(Boolean).join(". ")}><Textarea id={id} rows={3} className="font-mono text-xs" value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)} onChange={(e) => { try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); } }} /></Field>;
  }
  return <Field label={label} htmlFor={id} hint={hint}><Input id={id} value={value === undefined || value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value)} /></Field>;
}

/** Create or edit a data source with fields grouped per channel and a switch per channel. */
export function DataSourceForm({ open, onOpenChange, editing, adapters, projects, onSaved }: { open: boolean; onOpenChange: (open: boolean) => void; editing: DataSource | null; adapters: AdapterInfo[]; projects: ProjectWithRole[]; onSaved: (source: DataSource) => void }) {
  const { t } = useTranslation();
  const creatable = adapters.filter((a) => !a.builtin);
  // State is initialised once per mount; the page remounts the form (a fresh key) on every open.
  const [name, setName] = useState(editing?.name ?? "");
  const [adapterKey, setAdapterKey] = useState(editing?.adapter_key ?? "");
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);
  const [projectIds, setProjectIds] = useState<string[]>(editing?.project_ids ?? []);
  const [config, setConfig] = useState<Values>(() => (editing ? { ...(editing.config as Values) } : initialConfig(creatable[0])));
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  // A new source starts with the channels that need input switched off; the person turns
  // one on while filling it in. A stored source keeps its switches (absent means on).
  const [switches, setSwitches] = useState<Record<string, boolean>>(() => editing ? { ...((editing.channels ?? {}) as Record<string, boolean>) } : defaultSwitches(creatable[0]));
  const [error, setError] = useState<string | null>(null);
  const effectiveAdapterKey = adapterKey || creatable[0]?.key || "";
  const adapter = adapters.find((a) => a.key === effectiveAdapterKey);

  const properties = adapter?.config_schema.properties ?? {};
  const required = new Set(adapter?.config_schema.required ?? []);
  const keysOf = (c: AdapterChannel) => [...c.config_keys, ...(c.optional_keys ?? [])];
  const credentialKeysOf = (c: AdapterChannel) => [...c.credential_keys, ...(c.optional_credential_keys ?? [])];
  const channelKeys = new Set((adapter?.channels ?? []).flatMap(keysOf));
  const channelCredentials = new Set((adapter?.channels ?? []).flatMap(credentialKeysOf));
  const generalKeys = Object.keys(properties).filter((k) => !channelKeys.has(k));
  const generalCredentials = Object.keys(adapter?.credentials_schema ?? {}).filter((k) => !channelCredentials.has(k));
  const unknownKeys = Object.keys(config).filter((k) => !(k in properties));

  const save = useMutationToast({
    mutationFn: () => {
      const body: Record<string, unknown> = { name, enabled, config, project_ids: projectIds, channels: switches };
      const filledCredentials = Object.fromEntries(Object.entries(credentials).filter(([, v]) => v.trim() !== ""));
      if (Object.keys(filledCredentials).length > 0 || !editing) body.credentials = filledCredentials;
      if (!editing) body.adapter_key = effectiveAdapterKey;
      return editing ? api.patch<DataSource>(`/api/v1/data-sources/${editing.id}`, { body }) : api.post<DataSource>("/api/v1/data-sources", { body });
    },
    invalidate: [queryKeys.dataSources],
    success: editing ? "Data source saved" : "Data source created",
    onSuccess: (source) => { onOpenChange(false); onSaved(source); },
    onError: (e) => setError(e.message),
  });

  const setValue = (key: string, value: unknown) => setConfig((c) => { const next = { ...c }; if (value === undefined || value === "") delete next[key]; else next[key] = value; return next; });
  const channelOn = (c: AdapterChannel) => switches[c.key] !== false;
  const missingOf = (c: AdapterChannel) => [...c.config_keys.filter((k) => !isFilled(config[k])), ...c.credential_keys.filter((k) => !isFilled(credentials[k]) && !(editing?.has_credentials && !Object.values(credentials).some((v) => v.trim())))];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>{editing ? t("Edit data source") : t("New data source")}</DialogTitle><DialogDescription>{t("A source is its channels: switch each on or off and fill in what it needs. Credentials are encrypted and never shown again.")}</DialogDescription></DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("Name")} htmlFor="ds-name"><Input id="ds-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label={t("Adapter")} htmlFor="ds-adapter">
              <Select value={effectiveAdapterKey} disabled={Boolean(editing)} onValueChange={(v) => { setAdapterKey(v); const next = adapters.find((a) => a.key === v); setConfig(initialConfig(next)); setCredentials({}); setSwitches(defaultSwitches(next)); }}>
                <SelectTrigger id="ds-adapter"><SelectValue /></SelectTrigger>
                <SelectContent>{(editing ? adapters : creatable).map((a) => <SelectItem key={a.key} value={a.key}>{a.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
          </div>
          {adapter?.setup_hint && <Callout kind="info">{adapter.setup_hint}{adapter.push ? (adapter.webhook_token_in_query ? " The webhook URL with its token is shown after saving; the platform posts to that URL as is." : " The webhook URL and its bearer token are shown after saving.") : ""}</Callout>}

          {(adapter?.channels ?? []).map((c) => {
            const on = channelOn(c);
            const missing = on ? missingOf(c) : [];
            return (
              <section key={c.key} className="rounded-md border">
                <div className="flex items-start gap-3 border-b px-3 py-2">
                  <Switch id={`ch-${c.key}`} checked={on} onCheckedChange={(v) => setSwitches((s) => ({ ...s, [c.key]: v }))} aria-label={t("Channel {{name}} on", { name: c.label })} />
                  <label htmlFor={`ch-${c.key}`} className="min-w-0 flex-1 text-sm">
                    <span className="font-medium">{c.label}</span> <span className="text-xs text-muted-foreground">{c.direction === "in" ? t("inbound") : t("outbound")}</span>
                    <span className="block text-xs text-muted-foreground">{c.purpose}</span>
                  </label>
                  <StatusBadge value={!on ? "off" : missing.length ? "incomplete" : "ready"} />
                </div>
                {on && (
                  <div className="space-y-3 px-3 py-3">
                    {c.hint && <p className="text-xs text-muted-foreground">{c.hint}</p>}
                    {keysOf(c).filter((k) => k in properties).map((k) => <PropertyField key={k} id={`cfg-${k}`} name={k} prop={properties[k]} required={required.has(k) || c.config_keys.includes(k)} value={config[k]} onChange={(v) => setValue(k, v)} />)}
                    {credentialKeysOf(c).map((k) => <Field key={k} label={c.credential_keys.includes(k) ? `${k} *` : k} htmlFor={`cred-${k}`} hint={adapter?.credentials_schema[k] || undefined}><Input id={`cred-${k}`} type="password" autoComplete="off" placeholder={editing?.has_credentials ? t("stored, leave empty to keep") : ""} value={credentials[k] ?? ""} onChange={(e) => setCredentials((s) => ({ ...s, [k]: e.target.value }))} /></Field>)}
                    {keysOf(c).length === 0 && credentialKeysOf(c).length === 0 && <p className="text-xs text-muted-foreground">{t("Nothing to fill in.")}</p>}
                  </div>
                )}
              </section>
            );
          })}

          {(generalKeys.length > 0 || generalCredentials.length > 0) && (
            <section className="rounded-md border">
              <div className="border-b px-3 py-2 text-sm font-medium">{t("General settings")}</div>
              <div className="space-y-3 px-3 py-3">
                {generalKeys.map((k) => <PropertyField key={k} id={`cfg-${k}`} name={k} prop={properties[k]} required={required.has(k)} value={config[k]} onChange={(v) => setValue(k, v)} />)}
                {generalCredentials.map((k) => <Field key={k} label={k} htmlFor={`cred-${k}`} hint={adapter?.credentials_schema[k] || undefined}><Input id={`cred-${k}`} type="password" autoComplete="off" placeholder={editing?.has_credentials ? t("stored, leave empty to keep") : ""} value={credentials[k] ?? ""} onChange={(e) => setCredentials((s) => ({ ...s, [k]: e.target.value }))} /></Field>)}
              </div>
            </section>
          )}

          <Field label={t("Projects")} htmlFor="ds-projects" hint={t("Leave empty to attribute by device assignment; pick projects to scope this source to them.")}>
            <div className="flex flex-wrap gap-2" id="ds-projects">
              {projects.map((p) => { const on = projectIds.includes(p.id); return <Button key={p.id} type="button" size="sm" variant={on ? "default" : "outline"} onClick={() => setProjectIds(on ? projectIds.filter((x) => x !== p.id) : [...projectIds, p.id])}>{p.name}</Button>; })}
            </div>
          </Field>
          <div className="flex items-start gap-2"><Switch id="ds-enabled" checked={enabled} onCheckedChange={setEnabled} /><label htmlFor="ds-enabled" className="text-sm">{t("Enabled")}<span className="block text-xs text-muted-foreground">{t("Receives events: the webhook answers and the connector runs. Switch off to pause the source without deleting it.")}</span></label></div>
          {unknownKeys.length > 0 && <details className="text-xs"><summary className="cursor-pointer text-muted-foreground">{t("Other stored settings ({{count}})", { count: unknownKeys.length })}</summary><Textarea rows={4} className="mt-2 font-mono text-xs" value={JSON.stringify(Object.fromEntries(unknownKeys.map((k) => [k, config[k]])), null, 2)} readOnly /></details>}
          {error && <Callout kind="error">{error}</Callout>}
          <DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("Cancel")}</Button><Button type="submit" disabled={save.isPending || !name || !effectiveAdapterKey}>{editing ? t("Save") : t("Create")}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
