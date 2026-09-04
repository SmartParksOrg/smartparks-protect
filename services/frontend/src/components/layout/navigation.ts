/** Sidebar sections from architecture 28 (application navigation). Items without a route yet
 * render as disabled with the phase they arrive in. */
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Bell,
  Boxes,
  ChartLine,
  Cpu,
  Database,
  DatabaseBackup,
  FileClock,
  GitBranch,
  Layers,
  ListTree,
  Map as MapIcon,
  PawPrint,
  Plug,
  Radio,
  Ruler,
  ScrollText,
  Send,
  Settings2,
  Shield,
  SlidersHorizontal,
  TriangleAlert,
  Users,
  Waypoints,
  Workflow,
} from "lucide-react";

export interface NavItem {
  label: string;
  icon: LucideIcon;
  /** Relative to the project route, or absolute when it starts with `/`. */
  to?: string;
  phase?: number;
  adminOnly?: boolean;
  serverAdminOnly?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export const projectSections: NavSection[] = [
  {
    label: "Monitor",
    items: [
      { label: "Live map", icon: MapIcon, to: "map" },
      { label: "Entities", icon: PawPrint, to: "entities" },
      { label: "Devices", icon: Cpu, to: "devices" },
      { label: "Alerts", icon: Bell, to: "alerts" },
    ],
  },
  {
    label: "Analyze",
    items: [
      { label: "Data explorer", icon: ChartLine, to: "analyze/explorer" },
      { label: "Exports", icon: FileClock, to: "analyze/exports" },
    ],
  },
  {
    label: "Network",
    items: [
      { label: "Traffic", icon: Radio, to: "network/traffic" },
      { label: "Gateways", icon: Waypoints, to: "network/gateways" },
      { label: "Trace explorer", icon: ListTree, to: "network/traces" },
    ],
  },
  {
    label: "Rules",
    items: [
      { label: "Rules", icon: GitBranch, to: "rules" },
      { label: "Events", icon: Activity, to: "rules/events" },
      { label: "Automations", icon: Workflow, to: "rules/automations", adminOnly: true },
    ],
  },
  {
    label: "Integrate",
    items: [{ label: "Integrations", icon: Plug, to: "integrate/integrations", adminOnly: true }],
  },
  {
    label: "Control",
    items: [{ label: "Commands", icon: SlidersHorizontal, to: "control/commands" }],
  },
  {
    label: "Project admin",
    items: [
      { label: "Members", icon: Users, to: "admin/members", adminOnly: true },
      { label: "Features", icon: Layers, to: "admin/features", adminOnly: true },
      { label: "Notifications", icon: Send, to: "admin/notifications", adminOnly: true },
      { label: "Settings", icon: Settings2, to: "admin/settings", adminOnly: true },
    ],
  },
];

export const serverSections: NavSection[] = [
  {
    label: "Server admin",
    items: [
      { label: "Needs attention", icon: TriangleAlert, to: "/admin/attention", serverAdminOnly: true },
      { label: "System health", icon: Shield, to: "/admin/health", serverAdminOnly: true },
      { label: "Backup and recovery", icon: DatabaseBackup, to: "/admin/backups", serverAdminOnly: true },
      { label: "System alerts", icon: Bell, to: "/admin/alerts", serverAdminOnly: true },
      { label: "Automations", icon: Workflow, to: "/admin/automations", serverAdminOnly: true },
      { label: "Notifications", icon: Send, to: "/admin/notifications", serverAdminOnly: true },
      { label: "Projects", icon: Boxes, to: "/admin/projects", serverAdminOnly: true },
      { label: "Users", icon: Users, to: "/admin/users", serverAdminOnly: true },
      { label: "Devices", icon: Cpu, to: "/admin/devices", serverAdminOnly: true },
      { label: "Data sources", icon: Database, to: "/admin/data-sources", serverAdminOnly: true },
      { label: "Device types", icon: Cpu, to: "/admin/device-types", serverAdminOnly: true },
      { label: "Entity types", icon: PawPrint, to: "/admin/entity-types", serverAdminOnly: true },
      { label: "Metrics", icon: Ruler, to: "/admin/metrics", serverAdminOnly: true },
      { label: "Audit log", icon: ScrollText, to: "/admin/audit", serverAdminOnly: true },
    ],
  },
];
