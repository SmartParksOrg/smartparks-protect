import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Icon } from "@/components/icons/Icon";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import type {
  DeviceFeatureProperties,
  EntityFeatureProperties,
} from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { formatAgo, formatTime } from "@/lib/format";
import { projectFor } from "@/lib/scope";

/**
 * One panel for everything a person clicks on the live map (phase 19): the same header (picture
 * or icon, name as a link, a subtitle), a body of label and value rows, and a footer with the
 * actions. Entities, devices, track points and gateways each fill it with their own body, so a
 * click on anything reads the same and leads to the object.
 */
export function MapPanel({
  title,
  titleTo,
  subtitle,
  picture,
  note,
  onClose,
  panelOpen,
  children,
  footer,
}: {
  title: string;
  /** Where the name leads; no link when absent. */
  titleTo?: string;
  subtitle?: ReactNode;
  picture?: ReactNode;
  /** A line under the header, for example that the object was hidden until this visit. */
  note?: ReactNode;
  onClose: () => void;
  /** The layers panel is open, so the panel moves right of it on desktop. */
  panelOpen: boolean;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <aside
      className={`absolute bottom-3 right-3 z-10 max-h-[45%] overflow-y-auto rounded-lg border bg-card p-4 shadow-lg md:right-auto md:w-80 ${panelOpen ? "left-[23rem]" : "left-3"}`}
    >
      <div className="flex items-start gap-2">
        {picture}
        <div className="min-w-0 flex-1">
          {titleTo ? (
            <Link
              className="block truncate font-semibold underline-offset-2 hover:underline"
              to={titleTo}
            >
              {title}
            </Link>
          ) : (
            <div className="truncate font-semibold">{title}</div>
          )}
          {subtitle && (
            <div className="text-xs text-muted-foreground">{subtitle}</div>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("Close")}
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>
      {note && <div className="mt-2 text-xs text-muted-foreground">{note}</div>}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {children}
      </dl>
      {footer && (
        <div className="mt-3 flex flex-wrap items-center gap-2">{footer}</div>
      )}
    </aside>
  );
}

/** One label and value row of the panel body. */
export function PanelRow({
  label,
  children,
  title,
  className,
}: {
  label: string;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd title={title} className={className}>
        {children}
      </dd>
    </>
  );
}

function batteryClass(level: string | null | undefined): string {
  return level === "critical"
    ? "text-destructive"
    : level === "warn"
      ? "text-brand-sand"
      : "";
}

/** The battery, last status and last seen rows shared by entities and devices. */
function HealthRows({
  lastSeenAt,
  positionTime,
  batteryVoltage,
  healthLevel,
  lastStatusAt,
  now,
}: {
  lastSeenAt: string | null | undefined;
  positionTime: string | null | undefined;
  batteryVoltage: number | null | undefined;
  healthLevel: string | null | undefined;
  lastStatusAt: string | null | undefined;
  now: number;
}) {
  const { t } = useTranslation();
  return (
    <>
      <PanelRow label={t("Last seen")} title={formatTime(lastSeenAt)}>
        {formatAgo(lastSeenAt, now)}
      </PanelRow>
      <PanelRow label={t("Position")}>
        {positionTime ? formatTime(positionTime) : t("none yet")}
      </PanelRow>
      {batteryVoltage != null && (
        <PanelRow label={t("Battery")} className={batteryClass(healthLevel)}>
          {batteryVoltage.toFixed(2)} V
        </PanelRow>
      )}
      {lastStatusAt && (
        <PanelRow label={t("Last status")} title={formatTime(lastStatusAt)}>
          {formatAgo(lastStatusAt, now)}
        </PanelRow>
      )}
    </>
  );
}

/** A Show the track button with the count of points behind it. */
export function TrackButton({
  on,
  lengthLabel,
  returned,
  total,
  onToggle,
}: {
  on: boolean;
  lengthLabel: string;
  returned?: number;
  total?: number;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Button
        variant={on ? "default" : "outline"}
        size="sm"
        className="h-8"
        aria-pressed={on}
        title={t("Show the track, {{length}}", { length: lengthLabel })}
        onClick={onToggle}
      >
        {on ? t("Hide the track") : t("Show the track")}
      </Button>
      {returned != null && total != null && (
        <span className="text-xs text-muted-foreground">
          {t("{{returned}} of {{total}} points", { returned, total })}
        </span>
      )}
    </>
  );
}

export function EntityPanel({
  props,
  projectId,
  allProjects,
  projectName,
  now,
  wasHidden,
  panelOpen,
  onClose,
  tracked,
  trackLengthLabel,
  track,
  onToggleTrack,
}: {
  props: EntityFeatureProperties;
  projectId: string;
  allProjects: boolean;
  projectName: (id: string | null | undefined) => string;
  now: number;
  /** The entity was hidden in the layers panel and switched on for this visit. */
  wasHidden: boolean;
  panelOpen: boolean;
  onClose: () => void;
  tracked: boolean;
  trackLengthLabel: string;
  track?: { returned_points: number; total_points: number };
  onToggleTrack: () => void;
}) {
  const { t } = useTranslation();
  const project = projectFor(projectId, props.project_id);
  return (
    <MapPanel
      title={props.name}
      titleTo={`/projects/${project}/entities/${props.entity_id}`}
      subtitle={
        <>
          {props.entity_type}
          {allProjects && props.project_id
            ? ` · ${projectName(props.project_id)}`
            : ""}
        </>
      }
      picture={
        <ObjectPicture
          path={`/api/v1/projects/${project}/entities/${props.entity_id}/picture`}
          updatedAt={props.picture_updated_at}
          name={props.name}
          size="md"
          fallback={
            <Icon iconKey={props.icon_key} className="size-7 text-primary" />
          }
        />
      }
      note={
        wasHidden
          ? t("Hidden in the layers panel until now; it stays shown.")
          : undefined
      }
      onClose={onClose}
      panelOpen={panelOpen}
      footer={
        <TrackButton
          on={tracked}
          lengthLabel={trackLengthLabel}
          returned={track?.returned_points}
          total={track?.total_points}
          onToggle={onToggleTrack}
        />
      }
    >
      <HealthRows
        lastSeenAt={props.last_seen_at}
        positionTime={props.position_time}
        batteryVoltage={props.battery_voltage}
        healthLevel={props.health_level}
        lastStatusAt={props.last_status_at}
        now={now}
      />
      <PanelRow label={t("Device")}>
        {props.device_id ? (
          <Link
            className="underline"
            to={`/projects/${project}/devices/${props.device_id}`}
          >
            {t("open device")}
          </Link>
        ) : (
          t("none")
        )}
      </PanelRow>
      <PanelRow label={t("Alerts")}>
        {props.active_alert_count > 0 ? (
          <Link className="underline" to={`/projects/${projectId}/alerts`}>
            {props.active_alert_count} {t("open")}
          </Link>
        ) : (
          t("none")
        )}
      </PanelRow>
      <PanelRow label={t("More")}>
        <Link
          className="underline"
          to={`/projects/${project}/entities/${props.entity_id}?tab=data`}
        >
          {t("data")}
        </Link>
        {props.device_id && (
          <>
            {" · "}
            <Link
              className="underline"
              to={`/projects/${project}/devices/${props.device_id}?tab=network`}
            >
              {t("network")}
            </Link>
          </>
        )}
      </PanelRow>
    </MapPanel>
  );
}

export function DevicePanel({
  props,
  projectId,
  allProjects,
  projectName,
  now,
  wasHidden,
  panelOpen,
  onClose,
  tracked,
  trackLengthLabel,
  track,
  onToggleTrack,
}: {
  props: DeviceFeatureProperties;
  projectId: string;
  allProjects: boolean;
  projectName: (id: string | null | undefined) => string;
  now: number;
  wasHidden: boolean;
  panelOpen: boolean;
  onClose: () => void;
  tracked: boolean;
  trackLengthLabel: string;
  track?: { returned_points: number; total_points: number };
  onToggleTrack: () => void;
}) {
  const { t } = useTranslation();
  const devicePath =
    allProjects && !props.project_id
      ? `/admin/devices/${props.device_id}`
      : `/projects/${projectFor(projectId, props.project_id)}/devices/${props.device_id}`;
  return (
    <MapPanel
      title={props.name}
      titleTo={devicePath}
      subtitle={
        <>
          {props.device_type}
          {allProjects
            ? ` · ${props.project_id ? projectName(props.project_id) : t("Not in a project")}`
            : ""}
        </>
      }
      picture={
        <ObjectPicture
          path={`/api/v1/devices/${props.device_id}/picture`}
          updatedAt={props.picture_updated_at}
          name={props.name}
          size="md"
          fallback={
            <Icon iconKey={props.icon_key} className="size-7 text-primary" />
          }
        />
      }
      note={
        wasHidden
          ? t("Hidden in the layers panel until now; it stays shown.")
          : undefined
      }
      onClose={onClose}
      panelOpen={panelOpen}
      footer={
        <TrackButton
          on={tracked}
          lengthLabel={trackLengthLabel}
          returned={track?.returned_points}
          total={track?.total_points}
          onToggle={onToggleTrack}
        />
      }
    >
      <HealthRows
        lastSeenAt={props.last_seen_at}
        positionTime={props.position_time}
        batteryVoltage={props.battery_voltage}
        healthLevel={props.health_level}
        lastStatusAt={props.last_status_at}
        now={now}
      />
      {allProjects && !props.project_id && (
        <PanelRow label={t("Project")}>
          <Link className="underline" to={`/admin/devices/${props.device_id}`}>
            {t("none, assign under Server admin")}
          </Link>
        </PanelRow>
      )}
      <PanelRow label={t("Entity")}>
        {props.entity_id ? (
          <Link
            className="underline"
            to={`/projects/${projectFor(projectId, props.project_id)}/entities/${props.entity_id}`}
          >
            {props.entity_name}
          </Link>
        ) : (
          t("none")
        )}
      </PanelRow>
      <PanelRow label={t("More")}>
        <Link className="underline" to={`${devicePath}?tab=data`}>
          {t("data")}
        </Link>
        {" · "}
        <Link className="underline" to={`${devicePath}?tab=network`}>
          {t("network")}
        </Link>
      </PanelRow>
    </MapPanel>
  );
}
