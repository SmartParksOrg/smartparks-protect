/**
 * The settings file of the Smart Parks ble-settings-app on the browser's side (decision D426):
 * a flat JSON object of setting name to value. The server reads and writes the file
 * (`shared/device_drivers/opencollar/settings_file.py`); here a file's value is brought to the
 * form Protect keeps, so a file can be compared with what Protect knows before anything is
 * sent anywhere.
 */

/** A file's value as Protect keeps it: a boolean, a number, text, lower-case hex for bytes,
 * a PIN of digits as one byte per digit. Undefined when the value does not fit the type. */
export function fileValue(
  key: string,
  type: string,
  value: unknown,
): boolean | number | string | undefined {
  if (value === null || value === undefined || typeof value === "object")
    return undefined;
  const text = String(value).trim();
  const hexOf = (s: string) =>
    s
      .replace(/0x/gi, "")
      .replace(/[^0-9a-f]/gi, "")
      .toLowerCase();
  if (key === "device_pin") {
    if (/^\d{1,4}$/.test(text))
      return [...text.padStart(4, "0")].map((d) => `0${d}`).join("");
    return hexOf(text).length === 8 ? hexOf(text) : undefined;
  }
  if (type === "byte_array") return hexOf(text);
  if (type === "bool") {
    const lower = text.toLowerCase();
    if (lower === "true" || lower === "1") return true;
    if (lower === "false" || lower === "0") return false;
    return undefined;
  }
  if (type === "string") return text;
  const number = Number(text);
  return text !== "" && Number.isFinite(number) ? number : undefined;
}

/** The moment in the app's file name (`SP051463_20261127_101500.json`, the exporter's local
 * time), read as this browser's local time; none for another name or a moment yet to come. */
export function exportedAt(filename: string, now = new Date()): Date | null {
  const m = /_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.json$/i.exec(filename);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number);
  const at = new Date(y, mo - 1, d, h, mi, s);
  if (Number.isNaN(at.getTime()) || at.getMonth() !== mo - 1) return null;
  return at.getTime() <= now.getTime() ? at : null;
}

export interface KnownSetting {
  key: string;
  type: string;
  value?: unknown;
}

export interface FileDifference {
  key: string;
  type: string;
  /** The file's value in Protect's form; undefined when it does not fit the type. */
  file: boolean | number | string | undefined;
  /** What Protect knows; null when it knows nothing. */
  known: unknown;
}

export interface FileComparison {
  /** Settings of the file whose value differs from what Protect knows, or Protect knows none. */
  different: FileDifference[];
  same: number;
  /** Names in the file the catalogue of the device's firmware lacks. */
  unknown: string[];
}

/** A file against the settings Protect knows of the device, in the catalogue's order. */
export function compareFile(
  document: Record<string, unknown>,
  settings: KnownSetting[],
): FileComparison {
  const byKey = new Map(settings.map((s) => [s.key, s]));
  const result: FileComparison = { different: [], same: 0, unknown: [] };
  for (const key of Object.keys(document))
    if (!byKey.has(key)) result.unknown.push(key);
  for (const setting of settings) {
    if (!(setting.key in document)) continue;
    const file = fileValue(setting.key, setting.type, document[setting.key]);
    const known = setting.value ?? null;
    if (file !== undefined && known !== null && String(file) === String(known))
      result.same += 1;
    else
      result.different.push({ key: setting.key, type: setting.type, file, known });
  }
  return result;
}
