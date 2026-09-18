/** Sidebar sections from architecture 28 (application navigation). Items without a route yet
 * render as disabled with the phase they arrive in. */
import { t } from "@/lib/i18nMark";
import type { LucideIcon } from "lucide-react";

import type { PermissionKey } from "@/lib/permissions";
import {
  Activity,
  Bell,
  Bot,
  Boxes,
  ChartLine,
  Cpu,
  Database,
  DatabaseBackup,
  FileClock,
  FolderTree,
  Footprints,
  Gauge,
  GitBranch,
  Layers,
  LayoutDashboard,
  ListTree,
  Map as MapIcon,
  PawPrint,
  PenLine,
  Plug,
  Radio,
  Ruler,
  Satellite,
  ScrollText,
  Send,
  Settings2,
  Shield,
  SlidersHorizontal,
  TriangleAlert,
  Users,
  Waypoints,
  Wheat,
  Workflow,
} from "lucide-react";

export interface NavItem {
  label: string;
  icon: LucideIcon;
  /** Relative to the project route, or absolute when it starts with `/`. */
  to?: string;
  phase?: number;
  /** The permission key that shows the item (decision D188). */
  permission?: PermissionKey;
  /** An analysis module the project must offer for the item to show (plan, section 16). */
  module?: string;
  serverAdminOnly?: boolean;
  /** Works in the all-projects scope (decision D116); the rest is per project. */
  allScope?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
  /** The whole section needs this key (decision D134: the Network section is for project
   * admins, so it asks for project settings). */
  permission?: PermissionKey;
}

/** The sections as they apply to a scope: in the all scope only the items that work there. */
export function sectionsFor(allProjects: boolean): NavSection[] {
  if (!allProjects) return projectSections;
  return projectSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => item.allScope),
    }))
    .filter((section) => section.items.length > 0);
}

export const projectSections: NavSection[] = [
  {
    label: t("Monitor"),
    items: [
      { label: t("Live map"), allScope: true, icon: MapIcon, to: "map" },
      { label: t("Entities"), allScope: true, icon: PawPrint, to: "entities" },
      { label: t("Devices"), allScope: true, icon: Cpu, to: "devices" },
      { label: t("Alerts"), allScope: true, icon: Bell, to: "alerts" },
    ],
  },
  {
    label: t("Analyze"),
    items: [
      { label: t("Data explorer"), icon: ChartLine, to: "analyze/explorer" },
      { label: t("Exports"), icon: FileClock, to: "analyze/exports" },
      {
        label: t("Dashboards"),
        icon: LayoutDashboard,
        to: "analyze/dashboards",
      },
      { label: t("Curation"), icon: PenLine, to: "analyze/curation" },
      {
        label: t("Movement"),
        icon: Footprints,
        to: "analyze/movement",
        module: "movement",
      },
      {
        label: t("Grazing"),
        icon: Wheat,
        to: "analyze/grazing",
        module: "grazing",
      },
      {
        label: t("Device performance"),
        icon: Gauge,
        to: "analyze/device-performance",
        module: "device_performance",
      },
    ],
  },
  {
    label: t("Network"),
    permission: "project:write",
    items: [
      {
        label: t("Traffic"),
        allScope: true,
        icon: Radio,
        to: "network/traffic",
      },
      {
        label: t("Gateways"),
        allScope: true,
        icon: Waypoints,
        to: "network/gateways",
      },
      { label: t("Trace explorer"), icon: ListTree, to: "network/traces" },
    ],
  },
  {
    label: t("Rules"),
    items: [
      { label: t("Rules"), icon: GitBranch, to: "rules" },
      {
        label: t("Events"),
        allScope: true,
        icon: Activity,
        to: "rules/events",
      },
      {
        label: t("Automations"),
        icon: Workflow,
        to: "rules/automations",
        permission: "automations:write",
      },
    ],
  },
  {
    label: t("Integrate"),
    items: [
      {
        label: t("Integrations"),
        icon: Plug,
        to: "integrate/integrations",
        permission: "integrations:write",
      },
    ],
  },
  {
    label: t("Control"),
    items: [
      { label: t("Commands"), icon: SlidersHorizontal, to: "control/commands" },
    ],
  },
  {
    label: t("Project admin"),
    items: [
      {
        label: t("Members"),
        icon: Users,
        to: "admin/members",
        permission: "members:write",
      },
      {
        label: t("Features"),
        icon: Layers,
        to: "admin/features",
        permission: "features:write",
      },
      {
        label: t("Groups"),
        icon: FolderTree,
        to: "admin/groups",
        permission: "entities:write",
      },
      {
        label: t("Notifications"),
        icon: Send,
        to: "admin/notifications",
        permission: "project:write",
      },
      {
        label: t("Settings"),
        icon: Settings2,
        to: "admin/settings",
        permission: "project:write",
      },
    ],
  },
];

export const serverSections: NavSection[] = [
  {
    label: t("Server admin"),
    items: [
      {
        label: t("Needs attention"),
        icon: TriangleAlert,
        to: "/admin/attention",
        serverAdminOnly: true,
      },
      {
        label: t("System health"),
        icon: Shield,
        to: "/admin/health",
        serverAdminOnly: true,
      },
      {
        label: t("Traffic"),
        icon: Radio,
        to: "/admin/traffic",
        serverAdminOnly: true,
      },
      {
        label: t("Backup and recovery"),
        icon: DatabaseBackup,
        to: "/admin/backups",
        serverAdminOnly: true,
      },
      {
        label: t("System alerts"),
        icon: Bell,
        to: "/admin/alerts",
        serverAdminOnly: true,
      },
      {
        label: t("Automations"),
        icon: Workflow,
        to: "/admin/automations",
        serverAdminOnly: true,
      },
      {
        label: t("Notifications"),
        icon: Send,
        to: "/admin/notifications",
        serverAdminOnly: true,
      },
      {
        label: t("Projects"),
        icon: Boxes,
        to: "/admin/projects",
        serverAdminOnly: true,
      },
      {
        label: t("Users"),
        icon: Users,
        to: "/admin/users",
        serverAdminOnly: true,
      },
      {
        label: t("Devices"),
        icon: Cpu,
        to: "/admin/devices",
        serverAdminOnly: true,
      },
      {
        label: t("Data sources"),
        icon: Database,
        to: "/admin/data-sources",
        serverAdminOnly: true,
      },
      {
        label: t("Device types"),
        icon: Cpu,
        to: "/admin/device-types",
        serverAdminOnly: true,
      },
      {
        label: t("Entity types"),
        icon: PawPrint,
        to: "/admin/entity-types",
        serverAdminOnly: true,
      },
      {
        label: t("Metrics"),
        icon: Ruler,
        to: "/admin/metrics",
        serverAdminOnly: true,
      },
      {
        label: t("Audit log"),
        icon: ScrollText,
        to: "/admin/audit",
        serverAdminOnly: true,
      },
      {
        label: t("Environmental data"),
        icon: Satellite,
        to: "/admin/environment",
        serverAdminOnly: true,
      },
      {
        label: t("AI clients policy"),
        icon: Bot,
        to: "/admin/ai-policy",
        serverAdminOnly: true,
      },
    ],
  },
];
