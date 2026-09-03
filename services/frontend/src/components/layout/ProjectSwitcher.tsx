import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useProjects } from "@/hooks/useProjects";
import { cn } from "@/lib/utils";
import { useProjectStore } from "@/stores/project";

export function ProjectSwitcher() {
  const { projectId } = useParams();
  const { data } = useProjects();
  const navigate = useNavigate();
  const setLast = useProjectStore((s) => s.setLastProjectId);
  const [open, setOpen] = useState(false);
  const projects = data?.items ?? [];
  const current = projects.find((p) => p.id === projectId);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between">
          <span className="truncate">{current?.name ?? "Select a project"}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search projects" />
          <CommandList>
            <CommandEmpty>No project found.</CommandEmpty>
            <CommandGroup>
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
                  <Check className={cn("mr-2 size-4", project.id === projectId ? "opacity-100" : "opacity-0")} />
                  <span className="truncate">{project.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">{project.role.replace("project-", "")}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
