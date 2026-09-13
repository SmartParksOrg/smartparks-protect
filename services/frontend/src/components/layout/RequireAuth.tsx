import { useTranslation } from "react-i18next";
import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useParams } from "react-router";

import { usePermissions, useProjects } from "@/hooks/useProjects";
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

  if (!token || status === "expired" || status === "anonymous") {
    const from = encodeURIComponent(location.pathname + location.search);
    return (
      <Navigate
        to={`/login?from=${from}${status === "expired" ? "&expired=1" : ""}`}
        replace
      />
    );
  }
  if (status === "loading" || !useAuthStore.getState().user) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted-foreground">
        {t("Loading…")}
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
export function RequireProjectPermission({ permission }: { permission: PermissionKey }) {
  const { projectId } = useParams();
  const { can } = usePermissions(projectId);
  const { isPending } = useProjects();
  if (isPending) return null;
  if (!can(permission)) return <Navigate to={`/projects/${projectId}/map`} replace />;
  return <Outlet />;
}
