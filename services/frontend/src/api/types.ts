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
export type SeriesResponse = Schemas["SeriesResponse"];
export type Series = Schemas["Series"];
export type MeasurementRow = Schemas["MeasurementRow"];
export type MetricWithData = Schemas["MetricWithData"];
export type SavedView = Schemas["SavedViewRead"];
export type ExportJob = Schemas["ExportJobRead"];
export type ExportParameters = Schemas["ExportParameters"];
export type Rule = Schemas["RuleRead"];
export type RuleVersion = Schemas["RuleVersionRead"];
export type RuleTemplate = Schemas["RuleTemplateRead"];
export type ReplayResult = Schemas["ReplayResultRead"];
export type EventItem = Schemas["EventRead"];
export type EventDetail = Schemas["EventDetail"];
export type Alert = Schemas["AlertRead"];
export type Delivery = Schemas["ActionDeliveryRead"];
export type Automation = Schemas["AutomationRead"];
export type NotificationTarget = Schemas["NotificationTargetRead"];
export type NotificationCapabilities = Schemas["NotificationCapabilities"];
export type ActionAvailability = Schemas["ActionAvailability"];
export type CommandItem = Schemas["CommandRead"];
export type CommandDetail = Schemas["CommandDetail"];
export type CommandExecution = Schemas["CommandExecutionRead"];
export type QueueState = Schemas["QueueState"];
export type Integration = Schemas["IntegrationRead"];
export type IntegrationDetail = Schemas["IntegrationDetail"];
export type IntegrationDelivery = Schemas["IntegrationDeliveryRead"];
export type IntegrationDeliveryDetail = Schemas["IntegrationDeliveryDetail"];
export type IntegrationTestResult = Schemas["IntegrationTestResult"];
export type Gateway = Schemas["GatewayRead"];
export type GatewayDetail = Schemas["GatewayDetail"];
export type DeviceConnectivity = Schemas["DeviceConnectivity"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export type Role = "project-viewer" | "project-admin" | "server-admin";
