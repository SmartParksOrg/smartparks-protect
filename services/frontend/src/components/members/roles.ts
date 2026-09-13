import type { MemberScope } from "@/api/types";

/** The role and scope helpers the members page and the server admin's user page share
 * (decisions D186, D189): a role select value that tells a built-in role from a custom one,
 * the body a member update takes, and a one-line summary of what a member sees. */
export const CUSTOM = "custom:";
export const roleValue = (m: { role: string; role_id?: string | null }) =>
  m.role_id ? `${CUSTOM}${m.role_id}` : m.role;
export const roleBody = (value: string) =>
  value.startsWith(CUSTOM)
    ? { role_id: value.slice(CUSTOM.length) }
    : { role: value, role_id: null };

export function scopeSummary(
  scope: MemberScope | null | undefined,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  const groups = scope?.groups ?? [];
  const entities = scope?.entities ?? [];
  const devices = scope?.devices ?? [];
  if (!groups.length && !entities.length && !devices.length)
    return t("Everything");
  const parts: string[] = [];
  if (groups.length)
    parts.push(t("{{count}} groups", { count: groups.length }));
  if (entities.length)
    parts.push(t("{{count}} entities", { count: entities.length }));
  if (devices.length)
    parts.push(t("{{count}} devices", { count: devices.length }));
  return parts.join(", ");
}
