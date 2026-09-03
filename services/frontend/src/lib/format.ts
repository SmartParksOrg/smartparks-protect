/** Formatting helpers. Times display in the browser's timezone until the project setting exists. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

export function formatAgo(value: string | null | undefined): string {
  if (!value) return "never";
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function shortId(value: string | null | undefined, length = 8): string {
  return value ? value.slice(0, length) : "";
}
