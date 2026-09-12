import { useTranslation } from "react-i18next";
import { Menu, PanelLeftOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router";

import logoLandscape from "@/assets/brand/logo-landscape.webp";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { HealthDot } from "@/components/layout/HealthDot";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ALL_PROJECTS, isAllProjects } from "@/lib/scope";
import { useIconStore } from "@/stores/icons";
import { useLayoutStore } from "@/stores/layout";

/**
 * Fixed sidebar from 1024 px, a drawer below. The shell is exactly one viewport high and the main
 * area scrolls, so a page that wants the full height (the map) gets it with `flex-1` and pages
 * with long content scroll inside `main` (z-index ladder: map 0, sticky bar 30, drawer 50).
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
      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-card px-3 py-2 lg:hidden">
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("Open navigation")}
            onClick={() => setOpen(true)}
          >
            <Menu className="size-5" />
          </Button>
          <img src={logoLandscape} alt={t("Smart Parks Protect")} className="h-7 w-auto" />
          <HealthDot className="ml-auto" />
        </header>
        {/* the health dot in the top right corner of the content (decision D181), inside the
            10 px margin the map keeps around its strip */}
        <HealthDot className="absolute top-0 right-0 z-40 hidden lg:flex" />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
