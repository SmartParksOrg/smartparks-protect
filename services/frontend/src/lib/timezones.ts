import { browserTimezone, TIMEZONES } from "@/lib/analytics";

/** The IANA timezones a picker offers (Tim, 2026-09-16): every zone the browser knows, the
 * ones worth a first look at the top, each with its offset from UTC beside the name, and a
 * check that a name is a real zone so a typo never reaches the server. */

/** Every zone the browser knows; the short list of `TIMEZONES` when it cannot say. */
export function allTimezones(): string[] {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    if (zones.length) return [...new Set(["UTC", ...zones])];
  } catch {
    // an older browser
  }
  return [...TIMEZONES];
}

/** Whether `zone` names a timezone the browser can format in. */
export function isTimezone(zone: string): boolean {
  if (!zone) return false;
  // the browser's list is the authority where it exists: Intl also formats in legacy
  // abbreviations such as "CAT" or "EST", which the server refuses
  const known = allTimezones();
  if (known.length > TIMEZONES.length) return known.includes(zone);
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** The zone's offset from UTC at `at`, as "UTC+02:00"; empty when the browser cannot say. */
export function zoneOffset(zone: string, at: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      timeZoneName: "longOffset",
    }).formatToParts(at);
    const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    return name === "GMT" ? "UTC+00:00" : name.replace(/^GMT/, "UTC");
  } catch {
    return "";
  }
}

/** "Africa/Windhoek (UTC+02:00)"; the bare name when the offset is not known. */
export function zoneLabel(zone: string, at: Date = new Date()): string {
  const offset = zoneOffset(zone, at);
  return offset ? `${zone} (${offset})` : zone;
}

/** The zones to offer: `first` (the browser's zone, the project's, the ones other projects
 * use), then every other zone in name order; a `current` value the browser does not know
 * stays choosable so an edit does not lose it. */
export function orderedTimezones(
  first: string[] = [],
  current?: string,
): string[] {
  const head = [
    ...new Set([browserTimezone(), ...first, ...(current ? [current] : [])]),
  ].filter(Boolean);
  const rest = allTimezones()
    .filter((z) => !head.includes(z))
    .sort((a, b) => a.localeCompare(b));
  return [...head, ...rest];
}
