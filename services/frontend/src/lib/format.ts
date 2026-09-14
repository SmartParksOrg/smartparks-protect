/** Formatting helpers. Times display in the browser's timezone until the project setting exists. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

/** Compact form for narrow columns: the time alone for today, else a short date with the time. */
export function formatTimeShort(
  value: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!value) return "";
  const date = new Date(value);
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay)
    return date.toLocaleTimeString(undefined, { timeStyle: "medium" });
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatAgo(
  value: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!value) return "never";
  const seconds = Math.round((now - new Date(value).getTime()) / 1000);
  if (seconds < -60) return "clock ahead"; // a device time from the future (decision D119)
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

/** The instant a calendar day starts in a timezone, as ISO: assignment starts are dates for
 * people and moments for the system (decision D103). */
export function startOfDayIso(date: string, timeZone: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(guess));
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value ?? 0);
  const wall = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
  return new Date(guess - (wall - guess)).toISOString();
}

export function shortId(value: string | null | undefined, length = 8): string {
  return value ? value.slice(0, length) : "";
}

const CHANNEL_LABELS: Record<string, string> = {
  lorawan: "LoRaWAN",
  webble: "WebBLE",
  log_file: "log file",
  iridium: "Iridium",
  cellular: "cellular",
  api: "API",
  other: "other",
};

/** Acquisition channel names as people read them (architecture 25.1). */
export function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel;
}

/** Seconds as a duration people read: "5 d 3 h", "3 h 10 min", "42 s". Uptime and other
 * metrics in seconds are stored in seconds and shown this way (Tim, 2026-09-14). */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days} d ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min`;
  return `${total} s`;
}

/** A measurement with its unit, durations spelled out; the unit is part of the text. */
export function formatMeasurement(
  value: unknown,
  unit: string | null | undefined,
): string {
  if (typeof value === "number" && unit === "s") return formatDuration(value);
  if (typeof value !== "number") return String(value ?? "");
  const text = Number.isInteger(value)
    ? String(value)
    : Math.abs(value) >= 100
      ? value.toFixed(1)
      : value.toFixed(2);
  return unit ? `${text} ${unit}` : text;
}
