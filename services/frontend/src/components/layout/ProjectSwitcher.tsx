import { useTranslation } from "react-i18next";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useProjects } from "@/hooks/useProjects";
import { cn } from "@/lib/utils";
import { ALL_PROJECTS, isAllProjects } from "@/lib/scope";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

/** The project a page is about. It lives in the top bar (Tim, 2026-09-21), where the host
 * decides how wide it may be: the full width of a drawer, or a truncating button beside the
 * brand on a phone. */
export function ProjectSwitcher({ className }: { className?: string } = {}) {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const { data } = useProjects();
  const navigate = useNavigate();
  const setLast = useProjectStore((s) => s.setLastProjectId);
  const [open, setOpen] = useState(false);
  // an archived project is not somewhere to go; server admins find it under Projects
  const projects = (data?.items ?? []).filter((p) => !p.archived_at);
  const user = useAuthStore((s) => s.user);
  const all = isAllProjects(projectId);
  const current = projects.find((p) => p.id === projectId);
  const label = all
    ? t("All projects")
    : (current?.name ?? t("Select a project"));

  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn("w-full justify-between", className)}
        >
          <span className="truncate">{label}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      {/* wide enough for a name and its role on one line where there is room, and never
          wider than the screen (Tim, 2026-09-21) */}
      <PopoverContent
        className="w-[min(24rem,calc(100vw-1.5rem))] p-0 sm:w-80 lg:w-96"
        align="start"
      >
        <Command>
          <CommandInput placeholder={t("Search projects")} />
          <CommandList>
            <CommandEmpty>{t("No project found.")}</CommandEmpty>
            <CommandGroup>
              {user?.is_superuser && (
                <CommandItem
                  value={t("All projects")}
                  onSelect={() => {
                    setLast(ALL_PROJECTS);
                    setOpen(false);
                    void navigate(`/projects/${ALL_PROJECTS}/map`);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 size-4",
                      all ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{t("All projects")}</span>
                  <span className="ml-auto shrink-0 pl-2 text-xs whitespace-nowrap text-muted-foreground">
                    {t("server admin")}
                  </span>
                </CommandItem>
              )}
              {projects.map((project) => (
                <CommandItem
                  key={project.id}
                  value={project.name}
                  onSelect={() => {
                    setLast(project.id);
                    setOpen(false);
                    void navigate(`/projects/${project.id}/map`);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 size-4",
                      project.id === projectId ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <span className="truncate">{project.name}</span>
                  <span className="ml-auto shrink-0 pl-2 text-xs whitespace-nowrap text-muted-foreground">
                    {project.role.replace("project-", "")}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
