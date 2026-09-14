import i18n from "@/i18n";

/**
 * The permission keys as the interface knows them (decision D188): every gate asks `can(key)`
 * on the caller's keys from the project list, and the role editor shows the keys by area with
 * a label and a line of explanation each. The keys and the areas are the API's
 * (`shared/permissions.py`, `GET /permissions`); the words are here so they translate.
 */
export type PermissionKey =
  | "project:read"
  | "project:write"
  | "members:write"
  | "entities:write"
  | "devices:write"
  | "features:write"
  | "devices:control"
  | "devices:control_high_impact"
  | "rules:write"
  | "alerts:write"
  | "events:write"
  | "automations:write"
  | "integrations:write"
  | "data:curate"
  | "data:curate_bulk"
  | "data:approve"
  | "data:revert"
  | "traces:read"
  | "exports:create"
  | "views:write"
  | "dashboards:write"
  | "analysis:run";

export const BUILTIN_ROLES = [
  "project-viewer",
  "project-operator",
  "project-analyst",
  "project-admin",
] as const;
export type BuiltinRole = (typeof BUILTIN_ROLES)[number];

export function roleLabel(role: string): string {
  const t = i18n.t.bind(i18n);
  switch (role) {
    case "project-viewer":
      return t("Viewer");
    case "project-operator":
      return t("Operator");
    case "project-analyst":
      return t("Analyst");
    case "project-admin":
      return t("Admin");
    case "server-admin":
      return t("Server admin");
    default:
      return role;
  }
}

export function roleDescription(role: string): string {
  const t = i18n.t.bind(i18n);
  switch (role) {
    case "project-viewer":
      return t("Sees the project, reads traces, acknowledges alerts.");
    case "project-operator":
      return t("A viewer who also reports events, controls devices and draws features.");
    case "project-analyst":
      return t("An operator who also exports data and keeps saved views and dashboards.");
    case "project-admin":
      return t("Everything in the project, members and settings included.");
    default:
      return "";
  }
}

export function areaLabel(area: string): string {
  const t = i18n.t.bind(i18n);
  const labels: Record<string, string> = {
    see: t("See"),
    entities_and_devices: t("Entities and devices"),
    events_and_alerts: t("Events and alerts"),
    data_quality: t("Data quality"),
    rules_and_automations: t("Rules and automations"),
    integrations: t("Integrations"),
    exports_and_analysis: t("Exports and analysis"),
    control: t("Control"),
    members_and_settings: t("Members and settings"),
  };
  return labels[area] ?? area;
}

export function permissionLabel(key: string): string {
  const t = i18n.t.bind(i18n);
  const labels: Record<string, string> = {
    "project:read": t("See the project"),
    "traces:read": t("Read processing traces"),
    "entities:write": t("Create and edit entities and groups"),
    "devices:write": t("Assign devices"),
    "features:write": t("Draw and edit features"),
    "events:write": t("Report events"),
    "alerts:write": t("Acknowledge and resolve alerts"),
    "data:curate": t("Curate records"),
    "data:curate_bulk": t("Curate in bulk"),
    "data:approve": t("Approve curation"),
    "data:revert": t("Revert curation"),
    "rules:write": t("Edit rules"),
    "automations:write": t("Edit automations"),
    "integrations:write": t("Edit integrations"),
    "exports:create": t("Export data"),
    "views:write": t("Keep saved views"),
    "dashboards:write": t("Build dashboards"),
    "analysis:run": t("Run analyses"),
    "devices:control": t("Send commands to devices"),
    "devices:control_high_impact": t("Send high-impact commands"),
    "members:write": t("Manage members and roles"),
    "project:write": t("Change project settings"),
  };
  return labels[key] ?? key;
}

export function permissionHint(key: string): string {
  const t = i18n.t.bind(i18n);
  const hints: Record<string, string> = {
    "project:read": t("Always on: a member who cannot see the project is not a member."),
    "traces:read": t("The Trace explorer and the trace of a record."),
    "entities:write": t("Entities, their pictures and the group tree."),
    "devices:write": t("Assign a device to an entity or release it."),
    "features:write": t("Sites, zones, geofences and routes on the map."),
    "events:write": t("Manual events, such as a sighting."),
    "alerts:write": t("Take ownership of an alert and close it."),
    "data:curate": t("Mark records invalid or correct them one by one."),
    "data:curate_bulk": t("Curation jobs over many records."),
    "data:approve": t("Approve proposed curation."),
    "data:revert": t("Undo curation."),
    "rules:write": t("Rules that create events and alerts."),
    "automations:write": t("What happens after an event."),
    "integrations:write": t("Deliveries to other platforms."),
    "exports:create": t("Export jobs and direct downloads."),
    "views:write": t("Saved views on the explore page."),
    "dashboards:write": t("Dashboards of the project."),
    "analysis:run": t("Movement and grazing analyses and their kept results."),
    "devices:control": t("Status and position requests and settings."),
    "devices:control_high_impact": t("Commands that change how a device behaves for good."),
    "members:write": t("Invite people, set roles and scopes, compose roles."),
    "project:write": t("The project's name, settings, icons and notifications."),
  };
  return hints[key] ?? "";
}
