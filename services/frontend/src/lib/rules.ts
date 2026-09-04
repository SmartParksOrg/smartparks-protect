/** Helpers for the rule builder and the event screens: constants that mirror the backend
 * schema (`shared/rules/schema.py`), the flat form model and its conversion to a document. */

export type Scope = string; // a project id, or "server" for system events and server-level targets

export const scopeBase = (scope: Scope) => (scope === "server" ? "/api/v1/admin" : `/api/v1/projects/${scope}`);

export const SEVERITIES = ["info", "warning", "critical"] as const;
export const OPERATORS = ["<", "<=", ">", ">=", "==", "!="] as const;
export const TRIGGER_KINDS = [
  { value: "position", label: "Position", hint: "Every new position of a subject" },
  { value: "measurement", label: "Measurement", hint: "Every new value of a metric" },
  { value: "state", label: "Device state", hint: "Numeric entries of a device state change" },
  { value: "schedule", label: "Schedule", hint: "Checked on a timer, for no-data and window rules" },
] as const;
export const CONDITION_TYPES = [
  { value: "threshold", label: "Threshold" },
  { value: "spatial", label: "Geofence or area" },
  { value: "no_data", label: "No data" },
  { value: "window", label: "Window aggregate" },
] as const;
export const RELATIONS = ["enter", "exit", "inside", "outside"] as const;
export const FEATURE_TYPES = ["geofence", "zone", "site", "route"] as const;
export const AGGREGATES = ["avg", "min", "max", "sum", "count"] as const;
export const DERIVED_METRICS = ["speed_kmh", "speed_mps", "altitude_m"] as const;

export interface FormCondition {
  type: string;
  metric: string;
  op: string;
  value: number;
  relation: string;
  feature_type: string;
  feature_ids: string[];
  for_seconds: number;
  aggregate: string;
  seconds: number;
}

export interface RuleFormValues {
  trigger_kind: string;
  metric_key: string;
  every_seconds: number;
  entity_ids: string[];
  conditions: FormCondition[];
  for_seconds: number;
  cooldown_seconds: number;
  event_type: string;
  severity: string;
  title: string;
  description: string;
  create_alert: boolean;
}

export const emptyCondition = (type = "threshold"): FormCondition => ({
  type,
  metric: "battery_voltage",
  op: "<",
  value: 3.2,
  relation: "exit",
  feature_type: "geofence",
  feature_ids: [],
  for_seconds: 43200,
  aggregate: "avg",
  seconds: 21600,
});

export const defaultForm = (): RuleFormValues => ({
  trigger_kind: "measurement",
  metric_key: "battery_voltage",
  every_seconds: 300,
  entity_ids: [],
  conditions: [emptyCondition()],
  for_seconds: 0,
  cooldown_seconds: 0,
  event_type: "BATTERY_LOW",
  severity: "warning",
  title: "{entity} battery at {value} V",
  description: "",
  create_alert: true,
});

type Doc = Record<string, unknown>;

function leafToForm(leaf: Doc): FormCondition | null {
  const base = emptyCondition(String(leaf.type));
  switch (leaf.type) {
    case "threshold":
      return { ...base, metric: String(leaf.metric), op: String(leaf.op), value: Number(leaf.value) };
    case "spatial":
      return { ...base, relation: String(leaf.relation), feature_type: String(leaf.feature_type ?? ""), feature_ids: (leaf.feature_ids as string[] | undefined) ?? [] };
    case "no_data":
      return { ...base, for_seconds: Number(leaf.for_seconds) };
    case "window":
      return { ...base, metric: String(leaf.metric), aggregate: String(leaf.aggregate), seconds: Number(leaf.seconds), op: String(leaf.op), value: Number(leaf.value) };
    default:
      return null;
  }
}

/** A document the form can show: one leaf, or an `all` of leaves. Anything else returns null
 * and the editor falls back to JSON. */
export function documentToForm(doc: Doc): RuleFormValues | null {
  const trigger = (doc.trigger ?? {}) as Doc;
  const scope = (doc.scope ?? {}) as Doc;
  const event = (doc.event ?? {}) as Doc;
  const conditions = doc.conditions as Doc;
  const leaves = Array.isArray(conditions?.all) ? (conditions.all as Doc[]) : [conditions];
  const formConditions: FormCondition[] = [];
  for (const leaf of leaves) {
    const converted = leaf && typeof leaf === "object" ? leafToForm(leaf) : null;
    if (!converted) return null;
    formConditions.push(converted);
  }
  if ((scope.entity_type_ids as unknown[] | undefined)?.length || (scope.device_ids as unknown[] | undefined)?.length) return null;
  return {
    trigger_kind: String(trigger.kind ?? "measurement"),
    metric_key: String(trigger.metric_key ?? ""),
    every_seconds: Number(trigger.every_seconds ?? 300),
    entity_ids: ((scope.entity_ids as string[] | undefined) ?? []).map(String),
    conditions: formConditions,
    for_seconds: Number(doc.for_seconds ?? 0),
    cooldown_seconds: Number(doc.cooldown_seconds ?? 0),
    event_type: String(event.event_type ?? ""),
    severity: String(event.severity ?? "warning"),
    title: String(event.title ?? ""),
    description: String(event.description ?? ""),
    create_alert: Boolean(event.create_alert ?? true),
  };
}

function formLeaf(c: FormCondition): Doc {
  switch (c.type) {
    case "threshold":
      return { type: "threshold", metric: c.metric, op: c.op, value: c.value };
    case "spatial":
      return c.feature_ids.length > 0 ? { type: "spatial", relation: c.relation, feature_ids: c.feature_ids } : { type: "spatial", relation: c.relation, feature_type: c.feature_type };
    case "no_data":
      return { type: "no_data", for_seconds: c.for_seconds };
    case "window":
      return { type: "window", metric: c.metric, aggregate: c.aggregate, seconds: c.seconds, op: c.op, value: c.value };
    default:
      return { type: c.type };
  }
}

export function formToDocument(v: RuleFormValues): Doc {
  const trigger: Doc = { kind: v.trigger_kind };
  if (v.trigger_kind === "measurement" && v.metric_key) trigger.metric_key = v.metric_key;
  if (v.trigger_kind === "schedule") trigger.every_seconds = v.every_seconds;
  const leaves = v.conditions.map(formLeaf);
  const event: Doc = { event_type: v.event_type, severity: v.severity, title: v.title, create_alert: v.create_alert };
  if (v.description.trim()) event.description = v.description.trim();
  const doc: Doc = { trigger, conditions: leaves.length === 1 ? leaves[0] : { all: leaves }, event };
  if (v.entity_ids.length > 0) doc.scope = { entity_ids: v.entity_ids };
  if (v.for_seconds > 0) doc.for_seconds = v.for_seconds;
  if (v.cooldown_seconds > 0) doc.cooldown_seconds = v.cooldown_seconds;
  return doc;
}

export function describeDocument(doc: Doc): string {
  const trigger = (doc.trigger ?? {}) as Doc;
  const conditions = doc.conditions as Doc;
  const leaves = Array.isArray(conditions?.all) ? (conditions.all as Doc[]) : Array.isArray(conditions?.any) ? (conditions.any as Doc[]) : [conditions];
  const parts = leaves.map((l) => {
    switch (l?.type) {
      case "threshold":
        return `${String(l.metric)} ${String(l.op)} ${String(l.value)}`;
      case "spatial":
        return `${String(l.relation)} ${String(l.feature_type ?? "selected features")}`;
      case "no_data":
        return `no data for ${Math.round(Number(l.for_seconds) / 3600)} h`;
      case "window":
        return `${String(l.aggregate)}(${String(l.metric)}, ${Math.round(Number(l.seconds) / 3600)} h) ${String(l.op)} ${String(l.value)}`;
      default:
        return String(l?.type ?? "?");
    }
  });
  return `on ${String(trigger.kind)}${trigger.metric_key ? ` of ${String(trigger.metric_key)}` : ""}: ${parts.join(Array.isArray(conditions?.any) ? " or " : " and ")}`;
}

/** Marker icon for an event type, same mapping as the API's map layer. */
export function eventIcon(eventType: string): string {
  if (eventType.startsWith("GEOFENCE")) return "event.geofence";
  if (eventType === "NO_DATA" || eventType.startsWith("SYSTEM_")) return "event.device_offline";
  if (eventType === "SPECIES_DETECTION") return "event.detection";
  return "event.alert";
}

export const hoursLabel = (seconds: number) => (seconds % 3600 === 0 ? `${seconds / 3600} h` : seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`);
