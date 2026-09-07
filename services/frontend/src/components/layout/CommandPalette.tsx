import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Clock,
  Cpu,
  Database,
  FolderKanban,
  Layers,
  PawPrint,
  RadioTower,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { SearchHit, SearchResponse } from "@/api/types";
import { sectionsFor, serverSections } from "@/components/layout/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { useAuthStore } from "@/stores/auth";
import { isAllProjects } from "@/lib/scope";
import { useProjectStore } from "@/stores/project";

type Kind =
  | "entity"
  | "device"
  | "feature"
  | "gateway"
  | "data_source"
  | "project"
  | "page";

interface Recent {
  kind: Kind;
  id: string;
  name: string;
  subtitle: string | null;
  to: string;
}

const RECENT_KEY = "protect-recent-search";
const RECENT_MAX = 8;

function readRecent(): Recent[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as Recent[]) : [];
  } catch {
    return [];
  }
}

function remember(item: Recent): void {
  try {
    const next = [
      item,
      ...readRecent().filter(
        (r) => !(r.kind === item.kind && r.id === item.id),
      ),
    ].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // storage may be unavailable
  }
}

const ICONS: Record<Kind, typeof PawPrint> = {
  entity: PawPrint,
  device: Cpu,
  feature: Layers,
  gateway: RadioTower,
  data_source: Database,
  project: FolderKanban,
  page: Clock,
};

/** Where a hit leads. Entities, devices and features open inside their project; a gateway or a
 * data source has no page of its own yet and opens its list. */
function target(
  kind: Kind,
  hit: SearchHit,
  projectId: string | undefined,
): string {
  const pid = hit.project_id ?? projectId;
  switch (kind) {
    case "entity":
      return `/projects/${pid}/entities/${hit.id}`;
    case "device":
      return pid
        ? `/projects/${pid}/devices/${hit.id}`
        : `/admin/devices/${hit.id}`;
    case "feature":
      return `/projects/${pid}/map?feature=${hit.id}`;
    case "gateway":
      return pid ? `/projects/${pid}/network/gateways` : "/admin/gateways";
    case "data_source":
      return "/admin/data-sources";
    case "project":
      return `/projects/${hit.id}/map`;
    default:
      return "/";
  }
}

/** Ctrl+K (or Cmd+K) anywhere: one box over entities, devices, features, gateways, data sources,
 * projects and the pages of the current project, within what the user may see (decision D99).
 * The lists keep their own search boxes; this one answers "where is X". */
export function CommandPalette() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProject } = useParams();
  const lastProject = useProjectStore((s) => s.lastProjectId);
  const projectId = routeProject ?? lastProject ?? undefined;
  const role = useProjectRole(projectId);
  const user = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [recent, setRecent] = useState<Recent[]>([]);

  const openPalette = useCallback(() => {
    setRecent(readRecent());
    setQ("");
    setDebounced("");
    setOpen(true);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) setOpen(false);
        else openPalette();
      }
    };
    const onOpen = () => openPalette();
    window.addEventListener("keydown", onKey);
    window.addEventListener("protect:open-search", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("protect:open-search", onOpen);
    };
  }, [open, openPalette]);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(timer);
  }, [q]);

  const results = useQuery({
    queryKey: queryKeys.search(debounced),
    queryFn: () =>
      api.get<SearchResponse>("/api/v1/search", {
        query: { q: debounced, limit: 8 },
      }),
    enabled: open && debounced.length > 0,
    placeholderData: (previous) => previous,
  });
  const pages = useMemo(() => {
    const term = debounced.toLowerCase();
    const out: { label: string; to: string; icon: typeof PawPrint }[] = [];
    if (projectId)
      for (const section of sectionsFor(isAllProjects(projectId)))
        for (const item of section.items)
          if (item.to && (!item.adminOnly || canAdmin(role)))
            out.push({
              label: item.label,
              to: item.to.startsWith("/")
                ? item.to
                : `/projects/${projectId}/${item.to}`,
              icon: item.icon,
            });
    if (user?.is_superuser)
      for (const section of serverSections)
        for (const item of section.items)
          if (item.to)
            out.push({
              label: `${t("Server admin")}: ${item.label}`,
              to: item.to,
              icon: item.icon,
            });
    return term ? out.filter((p) => p.label.toLowerCase().includes(term)) : [];
  }, [debounced, projectId, role, user, t]);

  const go = (item: Recent) => {
    remember(item);
    setOpen(false);
    void navigate(item.to);
  };
  const group = (
    kind: Kind,
    heading: string,
    hits: SearchHit[] | undefined,
  ) => {
    if (!hits || hits.length === 0) return null;
    const Icon = ICONS[kind];
    return (
      <CommandGroup heading={heading} key={kind}>
        {hits.map((hit) => (
          <CommandItem
            key={`${kind}-${hit.id}`}
            value={`${kind}-${hit.id}`}
            onSelect={() =>
              go({
                kind,
                id: hit.id,
                name: hit.name,
                subtitle: hit.subtitle ?? null,
                to: target(kind, hit, projectId),
              })
            }
          >
            <Icon className="size-4 text-muted-foreground" />
            <span className="truncate">{hit.name}</span>
            {hit.subtitle && (
              <span className="ml-auto truncate text-xs text-muted-foreground">
                {hit.subtitle}
              </span>
            )}
          </CommandItem>
        ))}
      </CommandGroup>
    );
  };
  const r = results.data;
  const nothing =
    debounced &&
    r &&
    !results.isFetching &&
    pages.length === 0 &&
    [
      r.entities,
      r.devices,
      r.features,
      r.gateways,
      r.data_sources,
      r.projects,
    ].every((x) => (x ?? []).length === 0);
  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title={t("Search")}
      description={t(
        "Entities, devices, features, gateways, projects and pages",
      )}
      shouldFilter={false}
    >
      <CommandInput
        placeholder={t("Search everything…")}
        value={q}
        onValueChange={setQ}
      />
      <CommandList>
        {!debounced && recent.length > 0 && (
          <CommandGroup heading={t("Recent")}>
            {recent.map((item) => {
              const Icon = ICONS[item.kind];
              return (
                <CommandItem
                  key={`recent-${item.kind}-${item.id}`}
                  value={`recent-${item.kind}-${item.id}`}
                  onSelect={() => go(item)}
                >
                  <Icon className="size-4 text-muted-foreground" />
                  <span className="truncate">{item.name}</span>
                  {item.subtitle && (
                    <span className="ml-auto truncate text-xs text-muted-foreground">
                      {item.subtitle}
                    </span>
                  )}
                </CommandItem>
              );
            })}
          </CommandGroup>
        )}
        {!debounced && recent.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            {t("Type a name, a serial, a DevEUI or a page.")}
          </div>
        )}
        {nothing && <CommandEmpty>{t("Nothing found.")}</CommandEmpty>}
        {pages.length > 0 && (
          <CommandGroup heading={t("Pages")}>
            {pages.map((page) => (
              <CommandItem
                key={page.to}
                value={`page-${page.to}`}
                onSelect={() =>
                  go({
                    kind: "page",
                    id: page.to,
                    name: page.label,
                    subtitle: null,
                    to: page.to,
                  })
                }
              >
                <page.icon className="size-4 text-muted-foreground" />
                <span>{page.label}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {debounced && r && pages.length > 0 && <CommandSeparator />}
        {debounced && group("entity", t("Entities"), r?.entities)}
        {debounced && group("device", t("Devices"), r?.devices)}
        {debounced && group("feature", t("Features"), r?.features)}
        {debounced && group("gateway", t("Gateways"), r?.gateways)}
        {debounced &&
          group("data_source", t("Data sources"), r?.data_sources ?? [])}
        {debounced && group("project", t("Projects"), r?.projects)}
      </CommandList>
    </CommandDialog>
  );
}
