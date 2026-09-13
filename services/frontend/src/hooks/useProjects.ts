import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Page, ProjectWithRole } from "@/api/types";
import type { PermissionKey } from "@/lib/permissions";
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
export function useProjectRole(projectId: string | undefined): string | null {
  const user = useAuthStore((s) => s.user);
  const { project } = useProject(projectId);
  if (user?.is_superuser) return "server-admin";
  return project?.role ?? null;
}

/** The caller's permission keys in a project (decision D188): everything for a server admin,
 * else the keys the project list carries; `can` is the one gate the interface asks. */
export function usePermissions(projectId: string | undefined) {
  const user = useAuthStore((s) => s.user);
  const { project } = useProject(projectId);
  const all = Boolean(user?.is_superuser);
  const keys = new Set<string>(project?.permissions ?? []);
  const can = (key: PermissionKey): boolean => all || keys.has(key);
  return { can, all, keys, scopeLimited: Boolean(project?.scope_limited) };
}

/** Members and settings: the gate of the project admin pages. */
export const canAdmin = (role: string | null) =>
  role === "project-admin" || role === "server-admin";
