import { LogOut } from "lucide-react";
import { NavLink, useParams } from "react-router";

import LogoWide from "@/assets/brand/logo-wide.svg?react";
import { ProjectSwitcher } from "@/components/layout/ProjectSwitcher";
import { projectSections, serverSections, type NavItem } from "@/components/layout/navigation";
import { Button } from "@/components/ui/button";
import { canAdmin, useProjectRole } from "@/hooks/useProjects";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

function Item({ item, projectId, onNavigate }: { item: NavItem; projectId?: string; onNavigate?: () => void }) {
  const Icon = item.icon;
  if (!item.to) {
    return (
      <span
        className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm text-muted-foreground/60"
        title={`Arrives in phase ${item.phase}`}
      >
        <Icon className="size-4" />
        <span className="flex-1">{item.label}</span>
        <span className="text-[10px] uppercase tracking-wide">phase {item.phase}</span>
      </span>
    );
  }
  const to = item.to.startsWith("/") ? item.to : `/projects/${projectId}/${item.to}`;
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent",
          isActive ? "bg-primary text-primary-foreground hover:bg-primary" : "text-foreground",
        )
      }
    >
      <Icon className="size-4" />
      {item.label}
    </NavLink>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { projectId } = useParams();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const role = useProjectRole(projectId);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center px-4 py-4">
        <LogoWide className="h-8 w-auto text-primary" />
      </div>
      <div className="px-3 pb-3">
        <ProjectSwitcher />
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 pb-4">
        {projectId &&
          projectSections.map((section) => {
            const items = section.items.filter((item) => !item.adminOnly || canAdmin(role));
            if (items.length === 0) return null;
            return (
              <div key={section.label}>
                <div className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{section.label}</div>
                <div className="space-y-0.5">
                  {items.map((item) => (
                    <Item key={item.label} item={item} projectId={projectId} onNavigate={onNavigate} />
                  ))}
                </div>
              </div>
            );
          })}
        {user?.is_superuser &&
          serverSections.map((section) => (
            <div key={section.label}>
              <div className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{section.label}</div>
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <Item key={item.label} item={item} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          ))}
      </nav>
      <div className="border-t px-3 py-3">
        <div className="truncate px-3 text-xs text-muted-foreground" title={user?.email}>
          {user?.full_name || user?.email}
        </div>
        <Button variant="ghost" size="sm" className="mt-1 w-full justify-start" onClick={logout}>
          <LogOut className="size-4" /> Sign out
        </Button>
      </div>
    </div>
  );
}
