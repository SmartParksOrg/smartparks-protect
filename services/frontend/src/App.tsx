import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { AppLayout } from "@/components/layout/AppLayout";
import { RequireAuth, RequireServerAdmin } from "@/components/layout/RequireAuth";
import { ForgotPasswordPage, ResetPasswordPage } from "@/pages/auth/PasswordPages";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { ComingSoonPage } from "@/pages/ComingSoonPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ProjectsPage } from "@/pages/ProjectsPage";

const MapPage = lazy(() => import("@/pages/project/MapPage").then((m) => ({ default: m.MapPage })));
const EntitiesPage = lazy(() => import("@/pages/project/EntitiesPage").then((m) => ({ default: m.EntitiesPage })));
const DevicesPage = lazy(() => import("@/pages/project/DevicesPage").then((m) => ({ default: m.DevicesPage })));
const DevicePage = lazy(() => import("@/pages/project/DevicePage").then((m) => ({ default: m.DevicePage })));
const TrafficPage = lazy(() => import("@/pages/project/TrafficPage").then((m) => ({ default: m.TrafficPage })));
const TracesPage = lazy(() => import("@/pages/project/TracesPage").then((m) => ({ default: m.TracesPage })));
const ExplorerPage = lazy(() => import("@/pages/project/ExplorerPage").then((m) => ({ default: m.ExplorerPage })));
const ExportsPage = lazy(() => import("@/pages/project/ExportsPage").then((m) => ({ default: m.ExportsPage })));
const MembersPage = lazy(() => import("@/pages/project/MembersPage").then((m) => ({ default: m.MembersPage })));
const FeaturesPage = lazy(() => import("@/pages/project/FeaturesPage").then((m) => ({ default: m.FeaturesPage })));
const ProjectSettingsPage = lazy(() => import("@/pages/project/ProjectSettingsPage").then((m) => ({ default: m.ProjectSettingsPage })));
const AttentionPage = lazy(() => import("@/pages/admin/AttentionPage").then((m) => ({ default: m.AttentionPage })));
const HealthPage = lazy(() => import("@/pages/admin/HealthPage").then((m) => ({ default: m.HealthPage })));
const AdminProjectsPage = lazy(() => import("@/pages/admin/AdminProjectsPage").then((m) => ({ default: m.AdminProjectsPage })));
const UsersPage = lazy(() => import("@/pages/admin/UsersPage").then((m) => ({ default: m.UsersPage })));
const AdminDevicesPage = lazy(() => import("@/pages/admin/AdminDevicesPage").then((m) => ({ default: m.AdminDevicesPage })));
const DataSourcesPage = lazy(() => import("@/pages/admin/DataSourcesPage").then((m) => ({ default: m.DataSourcesPage })));
const DeviceTypesPage = lazy(() => import("@/pages/admin/CatalogPages").then((m) => ({ default: m.DeviceTypesPage })));
const EntityTypesPage = lazy(() => import("@/pages/admin/CatalogPages").then((m) => ({ default: m.EntityTypesPage })));
const MetricsPage = lazy(() => import("@/pages/admin/CatalogPages").then((m) => ({ default: m.MetricsPage })));
const AuditPage = lazy(() => import("@/pages/admin/AuditPage").then((m) => ({ default: m.AuditPage })));

function Loading() {
  return <div className="p-6 text-muted-foreground">Loading…</div>;
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Navigate to="/projects" replace />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId">
              <Route index element={<Navigate to="map" replace />} />
              <Route path="map" element={<MapPage />} />
              <Route path="entities" element={<EntitiesPage />} />
              <Route path="devices" element={<DevicesPage />} />
              <Route path="devices/:deviceId" element={<DevicePage />} />
              <Route path="alerts" element={<ComingSoonPage title="Alerts" phase={5} />} />
              <Route path="analyze/explorer" element={<ExplorerPage />} />
              <Route path="analyze/exports" element={<ExportsPage />} />
              <Route path="network/traffic" element={<TrafficPage />} />
              <Route path="network/traces" element={<TracesPage />} />
              <Route path="admin/members" element={<MembersPage />} />
              <Route path="admin/features" element={<FeaturesPage />} />
              <Route path="admin/settings" element={<ProjectSettingsPage />} />
            </Route>
            <Route path="/admin" element={<RequireServerAdmin />}>
              <Route index element={<Navigate to="attention" replace />} />
              <Route path="attention" element={<AttentionPage />} />
              <Route path="health" element={<HealthPage />} />
              <Route path="projects" element={<AdminProjectsPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="devices" element={<AdminDevicesPage />} />
              <Route path="devices/:deviceId" element={<DevicePage />} />
              <Route path="data-sources" element={<DataSourcesPage />} />
              <Route path="device-types" element={<DeviceTypesPage />} />
              <Route path="entity-types" element={<EntityTypesPage />} />
              <Route path="metrics" element={<MetricsPage />} />
              <Route path="audit" element={<AuditPage />} />
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
