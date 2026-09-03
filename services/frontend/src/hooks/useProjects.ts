import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Page, ProjectWithRole } from "@/api/types";
import { useAuthStore } from "@/stores/auth";

export function useProjects() {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: () => api.get<Page<ProjectWithRole>>("/api/v1/projects", { query: { limit: 500 } }),
    enabled: status === "authenticated",
  });
}

export function useProject(projectId: string | undefined) {
  const projects = useProjects();
  const project = projects.data?.items.find((p) => p.id === projectId) ?? null;
  return { ...projects, project };
}

/** The caller's role in a project: the membership role, or server-admin. */
export function useProjectRole(projectId: string | undefined): "project-viewer" | "project-admin" | "server-admin" | null {
  const user = useAuthStore((s) => s.user);
  const { project } = useProject(projectId);
  if (user?.is_superuser) return "server-admin";
  return (project?.role as "project-viewer" | "project-admin" | undefined) ?? null;
}

export const canAdmin = (role: string | null) => role === "project-admin" || role === "server-admin";
