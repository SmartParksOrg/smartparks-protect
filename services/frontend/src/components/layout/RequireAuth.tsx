import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { useAuthStore } from "@/stores/auth";

/** Loads the account once a token exists and redirects to login otherwise, remembering where the
 * user wanted to go. */
export function RequireAuth() {
  const { token, status, loadMe } = useAuthStore();
  const location = useLocation();

  useEffect(() => {
    if (token && status !== "authenticated" && status !== "loading") void loadMe();
  }, [token, status, loadMe]);

  if (!token || status === "expired" || status === "anonymous") {
    const from = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?from=${from}${status === "expired" ? "&expired=1" : ""}`} replace />;
  }
  if (status === "loading" || !useAuthStore.getState().user) {
    return <div className="flex min-h-screen items-center justify-center text-muted-foreground">Loading…</div>;
  }
  return <Outlet />;
}

export function RequireServerAdmin() {
  const user = useAuthStore((s) => s.user);
  if (!user?.is_superuser) return <Navigate to="/projects" replace />;
  return <Outlet />;
}
