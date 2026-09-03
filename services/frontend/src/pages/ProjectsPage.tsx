import { Navigate } from "react-router";

import { EmptyState } from "@/components/common/EmptyState";
import { Page } from "@/components/common/PageHeader";
import { useProjects } from "@/hooks/useProjects";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

/** Entry after login: open the last project, else the first, else say what to do. */
export function ProjectsPage() {
  const { data, isPending } = useProjects();
  const last = useProjectStore((s) => s.lastProjectId);
  const user = useAuthStore((s) => s.user);
  if (isPending) return <Page><div className="text-muted-foreground">Loading projects…</div></Page>;
  const projects = data?.items ?? [];
  const target = projects.find((p) => p.id === last) ?? projects[0];
  if (target) return <Navigate to={`/projects/${target.id}/map`} replace />;
  return (
    <Page>
      <EmptyState
        title="No project yet"
        description={user?.is_superuser ? "Create the first project under Server admin, Projects." : "You are not a member of any project. Ask a project admin to invite you."}
      />
    </Page>
  );
}
