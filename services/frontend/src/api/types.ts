/** Convenience aliases over the generated OpenAPI schema (`npm run generate:api`). */
import type { components } from "@/api/schema";

type Schemas = components["schemas"];

export type User = Schemas["UserRead"];
export type Project = Schemas["ProjectRead"];
export type ProjectWithRole = Schemas["ProjectWithRole"];
export type Member = Schemas["MemberRead"];
export type Invitation = Schemas["InvitationRead"];
export type EntityType = Schemas["EntityTypeRead"];
export type Entity = Schemas["EntityRead"];
export type Feature = Schemas["FeatureRead"];
export type DeviceType = Schemas["DeviceTypeRead"];
export type Device = Schemas["DeviceRead"];
export type DeviceDetail = Schemas["DeviceWithAssignments"];
export type DataSource = Schemas["DataSourceRead"];
export type ExternalIdentity = Schemas["ExternalIdentityRead"];
export type Metric = Schemas["MetricRead"];
export type UnknownIdentity = Schemas["UnknownIdentity"];
export type AttentionSummary = Schemas["AttentionSummary"];
export type DeadLetter = Schemas["DeadLetter"];
export type SourceEventSummary = Schemas["SourceEventSummary"];
export type SourceEvent = Schemas["SourceEventRead"];
export type Trace = Schemas["TraceRead"];
export type TraceSummary = Schemas["TraceSummary"];
export type TrafficRow = Schemas["TrafficRow"];
export type SystemHealth = Schemas["SystemHealth"];
export type Position = Schemas["PositionRead"];
export type Track = Schemas["TrackResponse"];
export type CurrentState = Schemas["CurrentStateResponse"];
export type AuditEntry = Schemas["AuditRead"];
export type UserAdmin = Schemas["UserAdminRead"];
export type InvitationInfo = Schemas["InvitationInfo"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export type Role = "project-viewer" | "project-admin" | "server-admin";
