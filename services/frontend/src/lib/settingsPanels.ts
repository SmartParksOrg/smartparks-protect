/**
 * A device's settings by topic (decision D432): the guided panels of the Smart Parks
 * ble-settings-app (`vendor/ble-settings-app`, decision D431) read against the values Protect
 * knows, as rows a page can draw. The app's renderer builds inputs in its own page; this is
 * Protect's reading of the same definitions, for showing first.
 *
 * Controls of the definitions read here: toggle, duration, utc-hour, select, choice, mode,
 * switch, hex, pin, datarate, byte, bytes, mac, text, hex-number, coordinate, ports, matrix,
 * and a field without a control (a number with its unit). `status` and `vhf-preview` belong
 * to a connected device in the app and are left out. A control this list lacks shows its
 * plain value, and the test on the definitions names it, so a sync that brings a new one is
 * noticed.
 */
import {
  type Condition,
  engine,
  type GetValue,
  type Panel,
  type PanelField,
  panels,
  portLabels,
  type PortRow,
  settingsMeta,
} from "@/vendor/ble-settings-app";

export const KNOWN_CONTROLS = new Set([
  "toggle",
  "duration",
  "utc-hour",
  "select",
  "choice",
  "mode",
  "switch",
  "hex",
  "pin",
  "datarate",
  "byte",
  "bytes",
  "mac",
  "text",
  "hex-number",
  "coordinate",
  "ports",
  "matrix",
  "status",
  "vhf-preview",
]);

/** Settings the app never puts in a settings file (`tracker_type`, `ble_adv`): a device
 * known from a file never has them, so a topic does not wait for them to say its sentence. */
const NEVER_IN_A_FILE = new Set(["tracker_type", "ble_adv"]);

/** Ports that carry no message type a flag can switch (the app's `skipPorts`). */
const SKIP_PORTS = new Set([
  "port_lr_messaging",
  "port_flash_log",
  "port_values",
  "port_messages",
  "port_commands",
]);

export interface SettingFact {
  key: string;
  type: string;
  value?: unknown;
}

export interface PanelContext {
  settings: SettingFact[];
  /** The catalogue addresses settings by family (firmware 7.4 and later). */
  families: boolean;
  ports: Record<string, number>;
  /** The firmware the device reported, "8.0"; none when unknown. */
  firmware: string | null;
}

export interface FieldRow {
  kind: "field";
  id: string;
  label: string;
  help: string;
  /** The value in words; null when Protect does not know it. */
  value: string | null;
  /** The firmware names behind the row. */
  keys: string[];
  /** The field has no meaning in the current choice; `reason` says why. */
  inactive: boolean;
  reason: string;
  warnings: string[];
  advanced: boolean;
}

export interface MatrixRow {
  kind: "matrix";
  id: string;
  label: string;
  help: string;
  columns: Array<{ key: string; label: string; known: boolean }>;
  ports: Array<{ number: number; label: string; set: boolean[] }>;
}

export interface GroupRow {
  kind: "group";
  id: string;
  title: string;
  help: string;
  advanced: boolean;
  summary: string;
  rows: Row[];
}

export type Row = FieldRow | MatrixRow | GroupRow;

export interface PanelView {
  id: string;
  title: string;
  description: string;
  beta: boolean;
  /** The topic in a sentence; empty when the panel has none or not every value is known. */
  summary: string;
  /** Settings of the topic Protect knows, and how many the topic has. */
  known: number;
  total: number;
  rows: Row[];
}

export function portRows(ports: Record<string, number>): PortRow[] {
  return Object.entries(ports)
    .filter(([name, number]) => Number.isFinite(number) && !SKIP_PORTS.has(name))
    .sort((a, b) => a[1] - b[1])
    .map(([name, number]) => ({
      name,
      number,
      label:
        portLabels[name] ?? name.replace(/^port_/, "").replace(/_/g, " "),
    }));
}

/** A UTC hour as the clock time here, "14:00". */
export function localTime(hour: unknown): string | null {
  const number = Number(hour);
  if (!Number.isFinite(number)) return null;
  const at = new Date();
  at.setUTCHours(Math.max(0, Math.min(23, Math.trunc(number))), 0, 0, 0);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

/** The setting's name for a person: the app's display name with a capital. */
export function displayName(key: string): string {
  const name = settingsMeta[key]?.display_name ?? key.replace(/_/g, " ");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function settingOptions(
  key: string,
  families: boolean,
): Array<{ value: number; label: string }> | null {
  const meta = settingsMeta[key];
  if (!meta) return null;
  return (families && meta.familyOptions) || meta.options || null;
}

function fieldKeys(field: PanelField): string[] {
  const keys = [...(field.keys ?? [])];
  if (field.key) keys.push(field.key);
  for (const column of field.columns ?? []) keys.push(column.key);
  return [...new Set(keys)];
}

function pinDigits(value: unknown): string {
  const pairs = String(value ?? "").match(/.{2}/g) ?? [];
  if (pairs.length !== 4 || pairs.some((p) => !/^0\d$/.test(p))) return "";
  return pairs.map((p) => p[1]).join("");
}

/** The settings a device of this firmware has: the catalogue of firmware 8 is the newest
 * release's, so a setting that came after the device's firmware (major.minor, as the status
 * reports it) is left out unless the device reported it anyway. */
export function settingsOfFirmware<
  T extends SettingFact & { since_firmware?: string | null },
>(settings: T[], firmware: string | null): T[] {
  const device = /^(\d+)\.(\d+)/.exec(firmware ?? "");
  if (!device) return settings;
  return settings.filter((setting) => {
    if (setting.value !== null && setting.value !== undefined) return true;
    const since = /^(\d+)\.(\d+)/.exec(setting.since_firmware ?? "");
    if (!since) return true;
    const [major, minor] = [Number(since[1]), Number(since[2])];
    return (
      major < Number(device[1]) ||
      (major === Number(device[1]) && minor <= Number(device[2]))
    );
  });
}

export function buildPanels(context: PanelContext): PanelView[] {
  const facts = new Map(context.settings.map((s) => [s.key, s]));
  const has = (key: string) => facts.has(key);
  const knows = (key: string) => {
    const value = facts.get(key)?.value;
    return value !== null && value !== undefined;
  };
  const getValue: GetValue = (key) => facts.get(key)?.value ?? undefined;
  const ports = portRows(context.ports);
  const formats = {
    localTime,
    options: (key: string) => settingOptions(key, context.families),
    pinDigits,
  };
  // a condition is only read when Protect knows every setting it asks about: an unknown
  // value would otherwise grey a field out for a reason that may not hold
  const decided = (condition: Condition | undefined) =>
    condition === undefined ||
    [...engine.conditionKeys(condition)].every(knows);
  const holds = (condition: Condition | undefined) =>
    engine.evaluateCondition(condition, getValue);

  function words(field: PanelField): string | null {
    const keys = fieldKeys(field).filter(has);
    if (keys.length === 0 || !keys.every(knows)) return null;
    const value = field.key ? getValue(field.key) : undefined;
    const number = engine.toNumber(value);
    const unit = field.unit ? ` ${field.unit}` : "";
    const off = () => field.offLabel ?? "Off";
    switch (field.control) {
      case "toggle":
        return engine.toBool(value) ? "On" : "Off";
      case "switch":
        return engine.isSwitchOn(field, getValue) ? "On" : "Off";
      case "choice":
      case "mode":
        return engine.resolveOption(field, getValue)?.label ?? null;
      case "duration": {
        if (number === 0) return off(); // an interval of 0 is off in the firmware
        return engine.formatDurationWords(
          number * (field.unit === "h" ? 3600 : 1),
        );
      }
      case "utc-hour":
        return `${engine.formatUtcHour(value)} UTC (${localTime(value)} here)`;
      case "select": {
        const option = settingOptions(field.key ?? "", context.families)?.find(
          (o) => o.value === number,
        );
        return option?.label ?? String(value);
      }
      case "datarate": {
        const text = engine.describeDataRate(
          getValue(field.regionKey ?? ""),
          value,
        );
        return `DR${number} = ${text ?? "not defined for this region"}`;
      }
      case "byte": {
        const byte = engine.byteAt(value, field.byte ?? 0);
        if (!Number.isFinite(byte)) return null;
        const option = field.options?.find((o) => o.value === byte);
        return option?.label ?? `${byte}${unit}`;
      }
      case "pin":
        return pinDigits(value) === "0000" ? "No PIN" : "Set";
      case "hex":
      case "bytes": {
        const hex = String(value).toUpperCase();
        if (field.secret) return /^0*$/.test(hex) ? "All zeros" : "Set (hidden)";
        return hex;
      }
      case "mac":
        return (String(value).toUpperCase().match(/.{1,2}/g) ?? []).join(":");
      case "hex-number":
        return `0x${number.toString(16).toUpperCase().padStart(4, "0")} (${number})`;
      case "coordinate":
        return (number / 1e7).toFixed(7);
      case "ports": {
        const set = ports.filter((p) => engine.isPortSet(value, p.number));
        return set.length === 0
          ? "None"
          : set.map((p) => `${p.label} (port ${p.number})`).join(", ");
      }
      default: {
        if (typeof value === "boolean") return value ? "On" : "Off";
        if (typeof value === "number") {
          if (value === 0 && field.zeroMeansOff) return off();
          return `${value}${unit}`;
        }
        return String(value);
      }
    }
  }

  function rowsOf(
    fields: PanelField[],
    path: string,
    inherited: { inactive: boolean; reason: string; advanced: boolean },
  ): Row[] {
    const rows: Row[] = [];
    fields.forEach((field, index) => {
      const id = `${path}.${index}`;
      if (field.control === "status" || field.control === "vhf-preview") return;
      if (
        field.visibleWhen !== undefined &&
        decided(field.visibleWhen) &&
        !holds(field.visibleWhen)
      )
        return;
      const gated =
        field.enabledWhen !== undefined &&
        decided(field.enabledWhen) &&
        !holds(field.enabledWhen);
      const state = {
        inactive: inherited.inactive || gated,
        reason: gated ? (field.reason ?? "") : inherited.reason,
        advanced: inherited.advanced || Boolean(field.advanced),
      };
      if (field.group !== undefined) {
        const inner = rowsOf(field.fields ?? [], id, state);
        if (inner.length === 0) return;
        const complete = allKeys(field.fields ?? []).every(knows);
        rows.push({
          kind: "group",
          id,
          title: field.group,
          help: field.help ?? "",
          advanced: Boolean(field.advanced),
          summary:
            field.summary === "fix-quality" && complete
              ? engine.describeFixQuality(getValue, formats)
              : "",
          rows: inner,
        });
        return;
      }
      if (field.control === "matrix") {
        const columns = (field.columns ?? []).filter((c) => has(c.key));
        if (columns.length === 0 || ports.length === 0) return;
        rows.push({
          kind: "matrix",
          id,
          label: field.label ?? "",
          help: field.help ?? "",
          columns: columns.map((c) => ({ ...c, known: knows(c.key) })),
          ports: ports.map((p) => ({
            number: p.number,
            label: p.label,
            set: columns.map(
              (c) => knows(c.key) && engine.isPortSet(getValue(c.key), p.number),
            ),
          })),
        });
        return;
      }
      const keys = fieldKeys(field).filter(has);
      if (keys.length === 0) return; // this firmware does not have the setting
      rows.push({
        kind: "field",
        id,
        label: field.label ?? displayName(keys[0]),
        help: field.help ?? settingsMeta[keys[0]]?.description ?? "",
        value: words(field),
        keys,
        inactive: state.inactive,
        reason: state.inactive ? state.reason : "",
        warnings: (field.warnings ?? [])
          .filter((w) => decided(w.when) && holds(w.when))
          .map((w) => w.text),
        advanced: state.advanced,
      });
    });
    return rows;
  }

  /** Every setting of this firmware the fields read. */
  function allKeys(fields: PanelField[]): string[] {
    const keys = new Set<string>();
    const walk = (list: PanelField[]) => {
      for (const field of list) {
        for (const key of fieldKeys(field)) if (has(key)) keys.add(key);
        if (field.fields) walk(field.fields);
      }
    };
    walk(fields);
    return [...keys];
  }

  function summaryOf(panel: Panel): string {
    const summary = panel.summary;
    if (!summary) return "";
    if (typeof summary === "object")
      return engine.describeSchedule(getValue, summary, formats);
    switch (summary) {
      case "positioning":
        return engine.describePositioning(getValue, formats);
      case "network":
        return engine.describeNetwork(getValue, formats);
      case "device":
        return engine.describeDevice(getValue, formats);
      case "lp0":
        return engine.describeLp0(getValue, formats);
      case "data": {
        const matrix = panel.fields.find((f) => f.control === "matrix");
        const columns = (matrix?.columns ?? []).filter((c) => has(c.key));
        return engine.describeDataFlags(getValue, ports, columns);
      }
      default:
        return "";
    }
  }

  const firmware = /^(\d+)\.(\d+)/.exec(context.firmware ?? "");
  const views: PanelView[] = [];
  for (const panel of panels) {
    if ((panel.requires ?? []).some((key) => !has(key))) continue;
    if (panel.minFirmware && firmware) {
      const [major, minor] = [Number(firmware[1]), Number(firmware[2])];
      const min = panel.minFirmware;
      if (major < min.major || (major === min.major && minor < min.minor))
        continue;
    }
    const rows = rowsOf(panel.fields, panel.id, {
      inactive: false,
      reason: "",
      advanced: false,
    });
    if (rows.length === 0) continue;
    const keys = allKeys(panel.fields).filter(
      (key) => knows(key) || !NEVER_IN_A_FILE.has(key),
    );
    const known = keys.filter(knows).length;
    // a topic the app gives no sentence says its first setting, which is its switch
    const first = rows[0];
    const state =
      first.kind === "field" && first.value !== null
        ? first.value.toLowerCase().includes(first.label.toLowerCase())
          ? `${first.value}.`
          : `${first.label}: ${first.value.charAt(0).toLowerCase()}${first.value.slice(1)}.`
        : "";
    views.push({
      id: panel.id,
      title: panel.title,
      description: panel.description ?? "",
      beta: Boolean(panel.beta),
      summary: known === keys.length ? summaryOf(panel) || state : "",
      known,
      total: keys.length,
      rows,
    });
  }
  return views;
}
