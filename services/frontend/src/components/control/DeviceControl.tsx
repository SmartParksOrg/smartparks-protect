import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ListOrdered, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { ActionAvailability, CommandDetail, CommandItem, QueueState, RouteOption } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { JsonView } from "@/components/common/JsonView";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useWebBle } from "@/hooks/useWebBle";
import { formatAgo, formatTime } from "@/lib/format";
import { fromHex, hex } from "@/lib/opencollar-ble";

const ROUTE_LABELS: Record<string, string> = { lorawan: "LoRaWAN", webble: "this browser (WebBLE)", iridium: "Iridium satellite", cellular: "cellular", api: "API", other: "other" };

type SchemaProperty = { type?: string; title?: string; description?: string; minimum?: number; maximum?: number; default?: unknown };

/** A small form generated from the action's parameter JSON schema: numbers, booleans, strings. */
function ParameterFields({ schema, values, onChange }: { schema: Record<string, unknown>; values: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void }) {
  const { t } = useTranslation();
  const properties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const entries = Object.entries(properties);
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">{t("This action takes no parameters.")}</p>;
  return (
    <div className="space-y-3">
      {entries.map(([key, prop]) => {
        const id = `param-${key}`;
        const hint = [prop.description, prop.minimum !== undefined ? `min ${prop.minimum}` : null, prop.maximum !== undefined ? `max ${prop.maximum}` : null].filter(Boolean).join(", ");
        if (prop.type === "boolean") return <div key={key} className="flex items-center gap-2"><Switch id={id} checked={Boolean(values[key])} onCheckedChange={(v) => onChange({ ...values, [key]: v })} /><label htmlFor={id} className="text-sm">{prop.title ?? key}</label></div>;
        const numeric = prop.type === "integer" || prop.type === "number";
        return (
          <Field key={key} label={prop.title ?? key} htmlFor={id} hint={hint || undefined}>
            <Input id={id} type={numeric ? "number" : "text"} step={prop.type === "integer" ? 1 : "any"} value={String(values[key] ?? "")} onChange={(e) => onChange({ ...values, [key]: numeric ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value })} />
          </Field>
        );
      })}
    </div>
  );
}

const STAGES = ["created", "encoded", "submitted", "accepted_by_network", "queued", "scheduled", "transmitted", "acknowledged", "confirmed_by_device"];

/** The lifecycle of one command: every stage the platform reported, nothing invented (architecture 17.4). */
export function CommandDetailDialog({ commandId, projectId, onClose }: { commandId: string | null; projectId?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const detail = useQuery({ queryKey: queryKeys.command(commandId ?? ""), queryFn: () => api.get<CommandDetail>(`/api/v1/commands/${commandId}`), enabled: Boolean(commandId), refetchInterval: (q) => (["failed", "expired", "confirmed_by_device"].includes(q.state.data?.command.status ?? "") ? false : 5_000) });
  const d = detail.data;
  const reached = new Set(d?.executions.map((e) => e.status));
  return (
    <Dialog open={commandId !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">{d?.command.action_key ?? "Command"} {d && <StatusBadge value={d.command.status} />}</DialogTitle>
          <DialogDescription>{d ? `${formatTime(d.command.created_at)} by ${d.command.actor.kind as string}${d.command.route ? `, over ${d.command.route}` : ""}` : "Loading…"}</DialogDescription>
        </DialogHeader>
        {detail.error && <Callout kind="error">{detail.error.message}</Callout>}
        {d && (
          <div className="space-y-4 text-sm">
            {d.command.error_message && <Callout kind={d.command.status === "expired" ? "warning" : "error"}>{d.command.error_message}</Callout>}
            <ol className="flex flex-wrap gap-1">
              {STAGES.map((stage) => <li key={stage} className={`rounded px-2 py-0.5 text-xs ${reached.has(stage) ? "bg-brand-green-light/40" : "bg-muted text-muted-foreground"}`}>{stage.replaceAll("_", " ")}</li>)}
            </ol>
            <div className="grid grid-cols-2 gap-2">
              <div><span className="text-muted-foreground">{t("Payload")}</span><div className="font-mono text-xs">{t("port")} {d.command.f_port ?? "?"}: {d.command.payload_hex ?? "not encoded"}</div></div>
              <div><span className="text-muted-foreground">{t("Platform reference")}</span><div className="font-mono text-xs">{d.command.provider_ref ?? "none"}</div></div>
              <div><span className="text-muted-foreground">{t("Expires")}</span><div>{formatTime(d.command.expires_at)}</div></div>
              {d.command.trace_id && projectId && <div><span className="text-muted-foreground">{t("Trace")}</span><div><Link className="underline" to={`/projects/${projectId}/network/traces?trace=${d.command.trace_id}`}>{t("view processing trace")}</Link></div></div>}
              {Object.keys(d.command.parameters).length > 0 && <div className="col-span-2"><span className="text-muted-foreground">{t("Parameters")}</span><JsonView value={d.command.parameters} /></div>}
              {Object.keys(d.command.result).length > 0 && <div className="col-span-2"><span className="text-muted-foreground">{t("Device response")}</span><JsonView value={d.command.result} /></div>}
            </div>
            <div>
              <div className="mb-1 font-medium">{t("Timeline")}</div>
              <ul className="divide-y">{d.executions.map((e) => <li key={e.id} className="flex flex-wrap items-center gap-2 py-1"><span className="w-40 whitespace-nowrap text-xs text-muted-foreground">{formatTime(e.time)}</span><StatusBadge value={e.status} /><span className="text-xs">{e.source}</span>{Object.keys(e.detail).length > 0 && <span className="text-xs text-muted-foreground">{JSON.stringify(e.detail)}</span>}</li>)}</ul>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Actions menu built from the device's capabilities with disabled reasons, the command dialog, history and the platform queue. */
export function DeviceControl({ deviceId, projectId, canFlush }: { deviceId: string; projectId?: string; canFlush: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const actions = useQuery({ queryKey: queryKeys.deviceActions(deviceId), queryFn: () => api.get<ActionAvailability[]>(`/api/v1/devices/${deviceId}/actions`) });
  const commands = useQuery({ queryKey: queryKeys.deviceCommands(deviceId), queryFn: () => api.get<CommandItem[]>(`/api/v1/devices/${deviceId}/commands`, { query: { limit: 20 } }), refetchInterval: 15_000 });
  const queue = useQuery({ queryKey: queryKeys.downlinkQueue(deviceId), queryFn: () => api.get<QueueState>(`/api/v1/devices/${deviceId}/downlink-queue`), refetchInterval: 30_000 });
  const routes = useQuery({ queryKey: queryKeys.deviceRoutes(deviceId), queryFn: () => api.get<RouteOption[]>(`/api/v1/devices/${deviceId}/routes`) });
  const ble = useWebBle(deviceId);
  const [chosen, setChosen] = useState<ActionAvailability | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [route, setRoute] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);
  const [flushing, setFlushing] = useState(false);
  // Routes the dialog offers (decision D79): every usable route; the browser route only while
  // this browser is connected to the device.
  const routeOptions = (routes.data ?? []).filter((r) => r.available && (!r.requires_client || (r.adapter_key === "webble" && ble.connection)));
  function openAction(a: ActionAvailability) {
    const defaults: Record<string, unknown> = {};
    for (const [k, p] of Object.entries((a.parameters_schema.properties ?? {}) as Record<string, SchemaProperty>)) if (p.default !== undefined) defaults[k] = p.default;
    setValues(defaults);
    setConfirmed(false);
    const preferred = ble.connection ? routeOptions.find((r) => r.adapter_key === "webble") : undefined;
    setRoute((preferred ?? routeOptions.find((r) => r.default) ?? routeOptions[0])?.data_source_id ?? "");
    setChosen(a);
  }
  /** A WebBLE command is written by this browser; the device's answer reaches the backend as a synced frame. */
  async function executeInBrowser(c: CommandItem) {
    const session = ble.session;
    if (!session || c.payload_hex == null || c.f_port == null) {
      await api.post(`/api/v1/commands/${c.id}/browser-result`, { body: { status: "failed", error_message: "the browser is not connected to the device" } }).catch(() => undefined);
      return;
    }
    try {
      const frame = new Uint8Array([c.f_port, ...fromHex(c.payload_hex)]);
      const answer = await session.writeEncoded(frame);
      await api.post(`/api/v1/commands/${c.id}/browser-result`, { body: { status: "transmitted", detail: { frame_hex: hex(frame), confirmation_hex: answer ? hex(answer.raw) : null, executed: answer ? answer.data[1] === 1 : null } } });
      await ble.sync("command", session);
    } catch (error) {
      await api.post(`/api/v1/commands/${c.id}/browser-result`, { body: { status: "failed", error_message: error instanceof Error ? error.message : String(error) } }).catch(() => undefined);
    }
    await client.invalidateQueries({ queryKey: queryKeys.deviceCommands(deviceId) });
  }
  const send = useMutationToast({
    mutationFn: (a: ActionAvailability) => api.post<CommandItem>(`/api/v1/devices/${deviceId}/commands`, { body: { action_key: a.key, parameters: values, confirmed, route_data_source_id: route || null } }),
    invalidate: [queryKeys.deviceCommands(deviceId), queryKeys.downlinkQueue(deviceId)],
    onSuccess: (c) => {
      setChosen(null);
      if (c.status === "failed") toast.error(`Command failed: ${c.error_message ?? c.error_code}`);
      else toast.success(`${c.action_key} ${c.status.replaceAll("_", " ")}${c.route ? ` over ${ROUTE_LABELS[c.route] ?? c.route}` : ""}`);
      setSelected(c.id);
      if (c.route === "webble" && c.status !== "failed") void executeInBrowser(c);
    },
  });
  const flush = useMutationToast({ mutationFn: () => api.delete<void>(`/api/v1/devices/${deviceId}/downlink-queue`), invalidate: [queryKeys.downlinkQueue(deviceId)], success: t("Downlink queue flushed"), onSuccess: () => setFlushing(false) });
  const available = actions.data ?? [];
  const needsConfirmation = chosen ? chosen.confirmation !== "none" : false;

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2"><Send className="size-4" /> {t("Control")}</CardTitle>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="sm" disabled={available.length === 0}>{t("Actions")} <ChevronDown className="size-4" /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              {available.map((a) => (
                <DropdownMenuItem key={a.key} disabled={!a.available || !a.permitted} onSelect={() => openAction(a)} title={!a.available ? (a.reason ?? undefined) : !a.permitted ? `Needs ${a.permission}` : a.description}>
                  <div><div>{a.label}</div>{(!a.available || !a.permitted) && <div className="text-xs text-muted-foreground">{!a.permitted ? `needs ${a.permission}` : a.reason}</div>}</div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {actions.isSuccess && available.length === 0 && <div className="text-muted-foreground">{t("This device type declares no control actions.")}</div>}
          {commands.data && commands.data.length === 0 && <div className="text-muted-foreground">{t("No commands yet.")}</div>}
          <ul className="divide-y">
            {commands.data?.map((c) => (
              <li key={c.id} className="flex cursor-pointer flex-wrap items-center gap-2 py-1.5 hover:bg-accent/40" onClick={() => setSelected(c.id)}>
                <span className="font-medium">{c.action_key}</span>
                <StatusBadge value={c.status} />
                <span className="text-xs text-muted-foreground">{t("{{ago}} by {{actor}}", { ago: formatAgo(c.created_at), actor: c.actor.kind as string })}</span>
                {c.error_message && <span className="text-xs text-destructive">{c.error_message}</span>}
              </li>
            ))}
          </ul>
          {queue.data?.supported && (
            <div className="flex flex-wrap items-center gap-2 border-t pt-2">
              <ListOrdered className="size-4 text-muted-foreground" />
              <span>{queue.data.items.length} {t("queued on the platform for")} {queue.data.external_id}</span>
              {queue.data.items.map((q) => <span key={q.id ?? q.data_hex} className="font-mono text-xs">{t("port")} {q.f_port}: {q.data_hex}{q.is_pending ? " (pending)" : ""}</span>)}
              {canFlush && queue.data.items.length > 0 && <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setFlushing(true)}><Trash2 className="size-4" /> {t("Flush")}</Button>}
            </div>
          )}
        </CardContent>
      </Card>
      <Dialog open={chosen !== null} onOpenChange={(o) => !o && setChosen(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{chosen?.label}</DialogTitle><DialogDescription>{chosen?.description}</DialogDescription></DialogHeader>
          {chosen && (
            <div className="space-y-3">
              <ParameterFields schema={chosen.parameters_schema} values={values} onChange={setValues} />
              {routeOptions.length > 0 && (
                <Field label={t("Route")} htmlFor="command-route" hint={routeOptions.length === 1 ? "The only route that can reach the device now" : "How the command reaches the device; the most recently seen route is preselected"}>
                  <Select value={route} onValueChange={setRoute}>
                    <SelectTrigger id="command-route"><SelectValue placeholder={t("Choose a route")} /></SelectTrigger>
                    <SelectContent>
                      {routeOptions.map((r) => <SelectItem key={r.data_source_id} value={r.data_source_id}>{ROUTE_LABELS[r.channel] ?? r.channel}: {r.name}{r.last_seen_at ? ` (seen ${formatAgo(r.last_seen_at)})` : ""}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
              )}
              {needsConfirmation && (
                <div className="flex items-start gap-2 rounded-md border border-brand-sand bg-brand-sand/20 p-2 text-sm">
                  <Switch id="confirm-command" checked={confirmed} onCheckedChange={setConfirmed} />
                  <label htmlFor="confirm-command">{chosen.confirmation === "privileged" ? "I understand this is a high-impact action on the device and want to send it." : "Send this command to the device."}</label>
                </div>
              )}
              {!chosen.confirms && <p className="text-xs text-muted-foreground">{t("The device sends no answer for this action; the lifecycle ends at the last stage the network reports.")}</p>}
            </div>
          )}
          <DialogFooter><Button variant="outline" onClick={() => setChosen(null)}>{t("Cancel")}</Button><Button disabled={send.isPending || (needsConfirmation && !confirmed)} onClick={() => chosen && send.mutate(chosen)}>{send.isPending ? "Sending…" : "Send"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={flushing} onOpenChange={setFlushing} title={t("Flush the platform's downlink queue?")} description={t("Every queued downlink is dropped; pending commands will expire.")} confirmLabel={t("Flush")} pending={flush.isPending} onConfirm={() => flush.mutate()} />
      <CommandDetailDialog commandId={selected} projectId={projectId} onClose={() => setSelected(null)} />
    </>
  );
}
