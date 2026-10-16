import { useTranslation } from "react-i18next";
import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router";

import { ServerUnavailableBar } from "@/components/layout/ServerUnavailableBar";

import {
  useAnalysisModules,
  usePermissions,
  useProjects,
} from "@/hooks/useProjects";
import type { PermissionKey } from "@/lib/permissions";
import { useAuthStore } from "@/stores/auth";

/** Loads the account once a token exists and redirects to login otherwise, remembering where the
 * user wanted to go. */
export function RequireAuth() {
  const { t } = useTranslation();
  const { token, status, loadMe } = useAuthStore();
  const location = useLocation();

  useEffect(() => {
    if (token && status !== "authenticated" && status !== "loading")
      void loadMe();
  }, [token, status, loadMe]);

  // a token with the start-up status is a session not loaded yet, not a stranger: the effect
  // above asks the server, and while the server is being updated (decision D329) the loading
  // screen says so instead of the login page
  if (!token || status === "expired") {
    const from = encodeURIComponent(location.pathname + location.search);
    return (
      <Navigate
        to={`/login?from=${from}${status === "expired" ? "&expired=1" : ""}`}
        replace
      />
    );
  }
  if (status === "loading" || !useAuthStore.getState().user) {
    // the bar says why the loading lasts when the server is being updated (decision D329)
    return (
      <div className="flex min-h-dvh flex-col">
        <ServerUnavailableBar />
        <div className="flex flex-1 items-center justify-center text-muted-foreground">
          {t("Loading…")}
        </div>
      </div>
    );
  }
  return <Outlet />;
}

export function RequireServerAdmin() {
  const user = useAuthStore((s) => s.user);
  if (!user?.is_superuser) return <Navigate to="/projects" replace />;
  return <Outlet />;
}

/** A project page behind a permission key (decision D188): a member without it lands on the
 * project's map instead of a page whose every request would be refused. */
export function RequireProjectPermission({
  permission,
}: {
  permission: PermissionKey;
}) {
  const { projectId } = useParams();
  const { can } = usePermissions(projectId);
  const { isPending } = useProjects();
  if (isPending) return null;
  if (!can(permission))
    return <Navigate to={`/projects/${projectId}/map`} replace />;
  return <Outlet />;
}

/** A page of an analysis module the project does not offer redirects to the map, so a switched
 * off module leaves no trace in the interface (docs/ANALYTICS_PHASE1_PLAN.md, section 16). */
export function RequireAnalysisModule({ module }: { module: string }) {
  const { projectId } = useParams();
  const modules = useAnalysisModules(projectId);
  const { isPending } = useProjects();
  if (isPending) return null;
  if (!modules.includes(module))
    return <Navigate to={`/projects/${projectId}/map`} replace />;
  return <Outlet />;
}
