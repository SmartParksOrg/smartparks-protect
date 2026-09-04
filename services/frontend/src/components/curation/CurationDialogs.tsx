import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { PenLine } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Correction, RecordHistory } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { invalidateRecords, useCurationSummary, useRecordHistory } from "@/hooks/useCuration";
import { type CurationTarget, FIELD_LABELS, formatValue, REASON_LABELS, toLocalInput } from "@/lib/curation";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

function initialInput(field: string, h: RecordHistory): { value: string; lat: string; lon: string; valid: boolean } {
  const c = (h.effective.coordinates ?? { latitude: 0, longitude: 0 }) as { latitude: number; longitude: number };
  return {
    value: field === "time" ? toLocalInput(String(h.effective.time)) : field === "value" ? String(h.effective.value ?? "") : "",
    lat: String(c.latitude),
    lon: String(c.longitude),
    valid: Boolean(h.effective.valid),
  };
}

/** The form of one correction; mounted once the history is known, so its state starts from
 * the effective values without effects. */
function CurateForm({ projectId, target, history, fields, reasons, requiresApproval, onDone }: { projectId: string; target: CurationTarget; history: RecordHistory; fields: string[]; reasons: string[]; requiresApproval: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const firstField = fields.includes("time") ? "time" : fields[0] ?? "valid";
  const [field, setFieldState] = useState(firstField);
  const [input, setInput] = useState(() => initialInput(firstField, history));
  const [reason, setReason] = useState("MANUAL_QC");
  const [comment, setComment] = useState("");
  const setField = (f: string) => { setFieldState(f); setInput(initialInput(f, history)); };
  const save = useMutationToast({
    mutationFn: () => {
      let corrected: unknown;
      if (field === "time") corrected = new Date(input.value).toISOString();
      else if (field === "coordinates") corrected = { latitude: Number(input.lat), longitude: Number(input.lon) };
      else if (field === "valid") corrected = input.valid;
      else corrected = Number(input.value);
      return api.post<Correction>(`/api/v1/projects/${projectId}/curation/corrections`, { body: { ...target, field, corrected_value: corrected, reason_code: reason, comment: comment || null } });
    },
    invalidate: [queryKeys.curationSummary(projectId)],
    onSuccess: (c) => { toast.success(c.status === "pending" ? "Correction proposed; it waits for approval" : "Correction applied"); invalidateRecords(client, projectId); onDone(); },
  });
  const h = history;
  return (
    <>
      <div className="space-y-3 text-sm">
        <div className="rounded-md border p-2 text-xs">
          <div>{t("Original time {{time}}", { time: formatTime(h.target_time) })}{h.curated_fields.length > 0 && <>{t("; curated: {{fields}}", { fields: h.curated_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ") })}</>}{!h.valid && t("; marked invalid")}</div>
          {h.corrections.length > 0 && <div className="text-muted-foreground">{h.corrections.length} {t("correction")}{h.corrections.length === 1 ? "" : "s"} {t("on record; version")} {h.curation_version}</div>}
        </div>
        <Field label={t("Field")} htmlFor="curate-field">
          <Select value={field} onValueChange={setField}>
            <SelectTrigger id="curate-field"><SelectValue /></SelectTrigger>
            <SelectContent>{fields.map((f) => <SelectItem key={f} value={f}>{FIELD_LABELS[f] ?? f}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <div className="text-xs text-muted-foreground">{t("Now: {{value}}", { value: formatValue(field, h.effective[field]) })}{h.curated_fields.includes(field) && <> {t("(originally {{value}})", { value: formatValue(field, h.original[field]) })}</>}</div>
        {field === "time" && <Field label={t("Corrected time (local)")} htmlFor="curate-time"><Input id="curate-time" type="datetime-local" step={1} value={input.value} onChange={(e) => setInput({ ...input, value: e.target.value })} /></Field>}
        {field === "value" && <Field label={t("Corrected value")} htmlFor="curate-value"><Input id="curate-value" type="number" step="any" value={input.value} onChange={(e) => setInput({ ...input, value: e.target.value })} /></Field>}
        {field === "coordinates" && <div className="grid grid-cols-2 gap-2"><Field label={t("Latitude")} htmlFor="curate-lat"><Input id="curate-lat" type="number" step="any" value={input.lat} onChange={(e) => setInput({ ...input, lat: e.target.value })} /></Field><Field label={t("Longitude")} htmlFor="curate-lon"><Input id="curate-lon" type="number" step="any" value={input.lon} onChange={(e) => setInput({ ...input, lon: e.target.value })} /></Field></div>}
        {field === "valid" && <div className="flex items-center gap-2"><Switch id="curate-valid" checked={input.valid} onCheckedChange={(v) => setInput({ ...input, valid: v })} /><label htmlFor="curate-valid">{input.valid ? "Valid: shown on maps, charts, rules and exports" : "Invalid: hidden from every normal view, kept in the record"}</label></div>}
        <Field label={t("Reason")} htmlFor="curate-reason">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger id="curate-reason"><SelectValue /></SelectTrigger>
            <SelectContent>{reasons.map((r) => <SelectItem key={r} value={r}>{REASON_LABELS[r] ?? r}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label={t("Comment or evidence")} htmlFor="curate-comment"><Textarea id="curate-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
        {requiresApproval && <Callout kind="info">{t("This project requires approval: the correction stays pending until another person approves it.")}</Callout>}
      </div>
      <DialogFooter><Button variant="outline" onClick={onDone}>{t("Cancel")}</Button><Button disabled={save.isPending} onClick={() => save.mutate()}>{requiresApproval ? "Propose" : "Apply"}</Button></DialogFooter>
    </>
  );
}

/** Correct one field of one record (architecture 28.2): the effective value before, the new
 * value, a structured reason and a comment. Applied at once or left pending per the project. */
export function CurateDialog({ projectId, target, onClose }: { projectId: string; target: CurationTarget | null; onClose: () => void }) {
  const { t } = useTranslation();
  const summary = useCurationSummary(projectId, target !== null);
  const history = useRecordHistory(projectId, target);
  const fields = summary.data?.curatable[target?.target_type ?? "position"] ?? ["time", "valid"];
  return (
    <Dialog open={target !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>{t("Curate")} {target?.target_type} {target?.target_id}</DialogTitle><DialogDescription>{t("The original stays in the record; the correction is an overlay with its reason and author, reversible at any time.")}</DialogDescription></DialogHeader>
        {history.isError && <Callout kind="error">{history.error.message}</Callout>}
        {history.isPending && target && <div className="text-sm text-muted-foreground">{t("Loading the record…")}</div>}
        {target && history.data && summary.data && (
          <CurateForm key={`${target.target_type}-${target.target_id}`} projectId={projectId} target={target} history={history.data} fields={fields} reasons={summary.data.reasons} requiresApproval={summary.data.requires_approval} onDone={onClose} />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** The history behind a curated record: effective versus original per field and every correction. */
export function RecordHistoryDialog({ projectId, target, onClose }: { projectId: string; target: CurationTarget | null; onClose: () => void }) {
  const { t } = useTranslation();
  const history = useRecordHistory(projectId, target);
  const h = history.data;
  return (
    <Dialog open={target !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{t("Curation history")}</DialogTitle><DialogDescription>{target && `${target.target_type} ${target.target_id}, original time ${formatTime(target.target_time)}`}</DialogDescription></DialogHeader>
        {history.isError && <Callout kind="error">{history.error.message}</Callout>}
        {h && (
          <div className="space-y-3 text-sm">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1">{t("Field")}</th><th>{t("Effective")}</th><th>{t("Original")}</th></tr></thead>
              <tbody>{Object.keys(h.effective).map((f) => <tr key={f} className="border-t"><td className="py-1">{FIELD_LABELS[f] ?? f}{h.curated_fields.includes(f) && <Badge variant="secondary" className="ml-1">{t("curated")}</Badge>}</td><td>{formatValue(f, h.effective[f])}</td><td className="text-muted-foreground">{formatValue(f, h.original[f])}</td></tr>)}</tbody>
            </table>
            <ul className="divide-y">
              {h.corrections.map((c) => (
                <li key={c.id} className="space-y-0.5 py-1.5">
                  <div className="flex flex-wrap items-center gap-2"><StatusBadge value={c.status} /><span className="font-medium">{FIELD_LABELS[c.field] ?? c.field}</span><span>{t("{{from}} to {{to}}", { from: formatValue(c.field, c.original_value), to: formatValue(c.field, c.corrected_value) })}</span></div>
                  <div className="text-xs text-muted-foreground">{REASON_LABELS[c.reason_code] ?? c.reason_code}{c.comment ? `: ${c.comment}` : ""}; {formatTime(c.created_at)}{c.curation_job_id ? ", bulk job" : ""}{c.reverted_at ? `; reverted ${formatTime(c.reverted_at)}` : ""}</div>
                </li>
              ))}
              {h.corrections.length === 0 && <li className="py-1 text-muted-foreground">{t("No corrections on this record.")}</li>}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Marks a curated or invalid record visibly (architecture 28.12); click opens the history. */
export function CuratedBadge({ curatedFields, valid, onClick }: { curatedFields: string[]; valid: boolean; onClick: () => void }) {
  if (curatedFields.length === 0 && valid) return null;
  return (
    <button type="button" className="inline-flex" onClick={(e) => { e.stopPropagation(); onClick(); }} title={`Curated: ${curatedFields.map((f) => FIELD_LABELS[f] ?? f).join(", ") || "validity"}`}>
      <Badge variant={valid ? "secondary" : "destructive"}><PenLine className="mr-1 size-3" />{valid ? "curated" : "invalid"}</Badge>
    </button>
  );
}
