import { useTranslation } from "react-i18next";
import { Menu, PanelLeftOpen, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router";

import logoLandscape from "@/assets/brand/logo-landscape.webp";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { HealthDot } from "@/components/layout/HealthDot";
import { ProjectSwitcher } from "@/components/layout/ProjectSwitcher";
import { ThemeSwitch } from "@/components/layout/ThemeSwitch";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ALL_PROJECTS, isAllProjects } from "@/lib/scope";
import { useIconStore } from "@/stores/icons";
import { useLayoutStore } from "@/stores/layout";

/**
 * Fixed sidebar from 1024 px, a drawer below. The shell is exactly one viewport high and the main
 * area scrolls, so a page that wants the full height (the map) gets it with `flex-1` and pages
 * with long content scroll inside `main` (z-index ladder: map 0, sticky bar 30, drawer 50). The
 * top bar on every screen size (decision D182) carries the landscape logo with the product name,
 * the project switcher and the search on the left, and the theme switch (D183) and the health
 * dot (D181) on the right. On a phone the product name steps aside for the project, and the
 * search shrinks to its icon; the palette it opens is the same one on every screen.
 */
export function AppLayout() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { projectId } = useParams();
  const loadIcons = useIconStore((s) => s.load);
  const sidebarHidden = useLayoutStore((s) => s.sidebarHidden);
  const setSidebarHidden = useLayoutStore((s) => s.setSidebarHidden);
  const location = useLocation();
  useEffect(() => {
    void loadIcons(projectId && !isAllProjects(projectId) ? projectId : null);
  }, [projectId, loadIcons]);
  // the all scope (decision D116) has the monitoring pages only; any other project page
  // opened with it goes to the map
  const allScopePage =
    /^\/projects\/all\/([a-z/]*)/.exec(location.pathname)?.[1] ?? null;
  if (
    allScopePage !== null &&
    ![
      "map",
      "entities",
      "devices",
      "alerts",
      "rules/events",
      "network/traffic",
      "network/gateways",
    ].includes(allScopePage)
  )
    return <Navigate to={`/projects/${ALL_PROJECTS}/map`} replace />;
  return (
    <div className="flex h-dvh">
      <CommandPalette />
      <aside
        className={`hidden w-64 shrink-0 border-r bg-card ${sidebarHidden ? "" : "lg:block"}`}
      >
        <div className="h-full">
          <Sidebar collapsible onCollapse={() => setSidebarHidden(true)} />
        </div>
      </aside>
      {sidebarHidden && (
        <div className="hidden w-10 shrink-0 flex-col items-center border-r bg-card py-2 lg:flex">
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("Show navigation")}
            title={t("Show navigation")}
            onClick={() => setSidebarHidden(false)}
          >
            <PanelLeftOpen className="size-5" />
          </Button>
        </div>
      )}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-72 p-0">
          <SheetTitle className="sr-only">{t("Navigation")}</SheetTitle>
          <Sidebar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* the top bar on every screen size (decision D182): the brand, the project switcher
            and the search (Tim, 2026-09-21: they belong where every page can see them, not at
            the top of a column that hides), the health dot (D181) and the theme switch (D183);
            the navigation button only where the sidebar is a drawer. Below `sm` the product
            name gives its room to the project, and the search becomes its icon. */}
        {/* 41 px on a phone, 53 px from tablet width up (Tim, 2026-09-13: every pixel of map counts) */}
        <header className="sticky top-0 z-30 flex items-center gap-1 border-b bg-card px-2 py-1 sm:gap-2 sm:px-3 sm:py-2">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 shrink-0 sm:size-9 lg:hidden"
            aria-label={t("Open navigation")}
            onClick={() => setOpen(true)}
          >
            <Menu className="size-5" />
          </Button>
          <img
            src={logoLandscape}
            alt=""
            className="h-6 w-auto shrink-0 sm:h-7"
          />
          <span className="hidden min-w-0 truncate text-sm font-medium whitespace-nowrap sm:inline sm:text-base">
            {t("Smart Parks Protect")}
          </span>
          <ProjectSwitcher className="h-8 w-auto min-w-0 flex-1 sm:ml-2 sm:h-9 sm:max-w-56 sm:flex-none lg:max-w-80" />
          <Button
            variant="outline"
            className="size-8 shrink-0 justify-center p-0 text-muted-foreground sm:h-9 sm:w-56 sm:justify-start sm:gap-2 sm:px-3"
            aria-label={t("Search…")}
            title={t("Search…")}
            onClick={() =>
              window.dispatchEvent(new Event("protect:open-search"))
            }
          >
            <Search className="size-4 shrink-0" />
            <span className="hidden flex-1 text-left sm:inline">
              {t("Search…")}
            </span>
            <kbd className="hidden rounded border bg-muted px-1.5 text-[10px] font-medium sm:inline">
              {t("Ctrl K")}
            </kbd>
          </Button>
          <span className="ml-auto flex shrink-0 items-center gap-1">
            <ThemeSwitch className="size-8 sm:size-9" />
            <HealthDot />
          </span>
        </header>
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
