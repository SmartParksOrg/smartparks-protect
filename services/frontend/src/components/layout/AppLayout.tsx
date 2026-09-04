import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { Outlet, useParams } from "react-router";

import LogoMark from "@/assets/brand/logo-mark.svg?react";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useIconStore } from "@/stores/icons";

/**
 * Fixed sidebar from 1024 px, a drawer below. The shell is exactly one viewport high and the main
 * area scrolls, so a page that wants the full height (the map) gets it with `flex-1` and pages
 * with long content scroll inside `main` (z-index ladder: map 0, sticky bar 30, drawer 50).
 */
export function AppLayout() {
  const [open, setOpen] = useState(false);
  const { projectId } = useParams();
  const loadIcons = useIconStore((s) => s.load);
  useEffect(() => { void loadIcons(projectId ?? null); }, [projectId, loadIcons]);
  return (
    <div className="flex h-screen">
      <aside className="hidden w-64 shrink-0 border-r bg-card lg:block">
        <div className="h-full">
          <Sidebar />
        </div>
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-72 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-card px-3 py-2 lg:hidden">
          <Button variant="ghost" size="icon" aria-label="Open navigation" onClick={() => setOpen(true)}>
            <Menu className="size-5" />
          </Button>
          <LogoMark className="h-6 w-auto text-primary" />
          <span className="font-medium">Smart Parks Protect</span>
        </header>
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
