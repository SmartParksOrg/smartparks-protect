/**
 * The guided settings panels of the Smart Parks ble-settings-app, as Protect uses them
 * (decision D431). The three files beside this one are copied byte for byte from the app at
 * the commit in `pin.json` by `scripts/sync_settings_panels.py` and are never edited here; the
 * app releases them under MIT as well (`LICENSE-MIT-panels.md`). The two scripts are written
 * for a classic script tag and for Node at once: in the browser they hang their API on the
 * global object, under a CommonJS loader (the tests) they export it. Both are read here, typed
 * by what Protect uses of them.
 */
import * as engineFile from "./panel-engine.js";
import * as definitionsFile from "./panel-definitions.js";

import meta from "./settings-meta.json";
import pin from "./pin.json";

export type GetValue = (key: string) => unknown;

/** A condition of the panel definitions; the engine evaluates it. */
export type Condition = boolean | Record<string, unknown>;

export interface FieldOption {
  id?: string;
  value?: number;
  label: string;
  help?: string;
  when?: Condition;
}

export interface PanelField {
  key?: string;
  keys?: string[];
  control?: string;
  label?: string;
  help?: string;
  unit?: string;
  byte?: number;
  secret?: boolean;
  regionKey?: string;
  zeroMeansOff?: boolean;
  offLabel?: string;
  advanced?: boolean;
  enabledWhen?: Condition;
  visibleWhen?: Condition;
  dependsOn?: Condition;
  reason?: string;
  on?: Condition;
  options?: FieldOption[];
  columns?: Array<{ key: string; label: string; summaryLabel?: string }>;
  warnings?: Array<{ when: Condition; text: string }>;
  /** A group: a title with fields of its own. */
  group?: string;
  summary?: string;
  fields?: PanelField[];
}

export interface ScheduleSummary {
  type: "schedule";
  enabledKey?: string;
  interval1Key: string;
  multipleKey: string;
  start1Key: string;
  interval2Key: string;
  start2Key: string;
  verb?: string;
  subject?: string;
}

export interface Panel {
  id: string;
  title: string;
  description?: string;
  beta?: boolean;
  requires?: string[];
  minFirmware?: { major: number; minor: number };
  summary?: string | ScheduleSummary;
  fields: PanelField[];
}

export interface PortRow {
  name: string;
  number: number;
  label: string;
}

interface Formats {
  localTime?: (hour: unknown) => string | null;
  options?: (key: string) => Array<{ value: number; label: string }> | null;
  pinDigits?: (value: unknown) => string;
}

export interface Engine {
  toBool(value: unknown): boolean;
  toNumber(value: unknown): number;
  evaluateCondition(condition: Condition | undefined, getValue: GetValue): boolean;
  conditionKeys(condition: Condition | undefined): Set<string>;
  planWriteOrder<T extends { key: string; value: unknown }>(
    changes: T[],
    definitions: Panel[],
  ): T[];
  resolveOption(field: PanelField, getValue: GetValue): FieldOption | null;
  isSwitchOn(field: PanelField, getValue: GetValue): boolean;
  formatDurationWords(seconds: unknown): string;
  formatUtcHour(hour: unknown): string;
  describePositioning(getValue: GetValue, fmt?: Formats): string;
  describeSchedule(getValue: GetValue, cfg: ScheduleSummary, fmt?: Formats): string;
  describeFixQuality(getValue: GetValue, fmt?: Formats): string;
  describeNetwork(getValue: GetValue, fmt?: Formats): string;
  describeDevice(getValue: GetValue, fmt?: Formats): string;
  describeDataFlags(
    getValue: GetValue,
    ports: PortRow[],
    columns: Array<{ key: string; label: string; summaryLabel?: string }>,
  ): string;
  describeLp0(getValue: GetValue, fmt?: Formats): string;
  describeDataRate(region: unknown, dataRate: unknown): string | null;
  byteAt(value: unknown, index: number): number;
  isPortSet(mask: unknown, port: number): boolean;
}

export interface SettingMeta {
  category: string;
  label: string;
  description: string;
  display_name: string;
  options?: Array<{ value: number; label: string }>;
  familyOptions?: Array<{ value: number; label: string }>;
}

interface Definitions {
  version: number;
  panels: Panel[];
  portLabels: Record<string, string>;
}

const scope = globalThis as unknown as {
  PanelEngine?: Engine;
  PanelDefinitions?: Definitions;
};

function loaded<T>(file: object, global: T | undefined, name: string): T {
  const exported = (file as { default?: T }).default;
  const api = global ?? exported;
  if (!api) throw new Error(`${name} of the ble-settings-app did not load`);
  return api;
}

const definitions = loaded(
  definitionsFile,
  scope.PanelDefinitions,
  "panel-definitions.js",
);

export const engine: Engine = loaded(
  engineFile,
  scope.PanelEngine,
  "panel-engine.js",
);
export const panels: Panel[] = definitions.panels;
export const portLabels: Record<string, string> =
  definitions.portLabels;
export const settingsMeta = meta.settings as unknown as Record<
  string,
  SettingMeta
>;
export const categories = meta.categories as Record<
  string,
  { title: string; order: number; settings: string[] }
>;
/** The commit of the ble-settings-app these files were copied from. */
export const pinnedCommit: string = pin.commit;
