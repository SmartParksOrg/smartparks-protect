import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Copy,
  Crosshair,
  Flame,
  Route,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { Icon } from "@/components/icons/Icon";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import type {
  DeviceFeatureProperties,
  EntityFeatureProperties,
} from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { useIsPhone } from "@/hooks/useMediaQuery";
import {
  BatteryTrend,
  BatteryValue,
  ContactsTrend,
  MovementTrend,
  MovementValue,
  UptimeTrend,
  UptimeValue,
} from "@/components/map/BatteryTrend";
import { movementLevel } from "@/lib/movement";
import { imprecise } from "@/lib/accuracy";
import { formatAgo, formatTime } from "@/lib/format";
import {
  isDeviceFix,
  positionKindExplanation,
  positionKindLabel,
} from "@/lib/positionKind";
import { projectFor } from "@/lib/scope";

/**
 * One panel for everything a person clicks on the live map (phase 19): the same header (picture
 * or icon, name as a link, a subtitle), a body of label and value rows, and a footer with the
 * actions. Entities, devices, track points and gateways each fill it with their own body, so a
 * click on anything reads the same and leads to the object. `TrackButton` and `HeatButton` are
 * the icon toggles the entity and device panels carry, the same ones as the layers panel's rows.
 */
export function MapPanel({
  title,
  titleTo,
  subtitle,
  picture,
  note,
  summary,
  onClose,
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
  /** The one-line state shown on a phone instead of the rows until the panel is unfolded
   * (Tim, 2026-09-13: the rows never fit a small screen). */
  summary?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const { t } = useTranslation();
  const phone = useIsPhone();
  // unfolded for one object; a new object starts folded again without an effect
  const [unfoldedFor, setUnfoldedFor] = useState<string | null>(null);
  const foldable = phone && summary != null;
  const folded = foldable && unfoldedFor !== title;
  return (
    // the panel is a shell and an inner box scrolls: a scrolling box with a background in the
    // page's fixed-height column paints its colour far below itself in Chromium
    <aside className="flex max-h-[45vh] shrink-0 flex-col rounded-lg border bg-card shadow-lg sm:max-h-[calc(100vh-9rem)]">
      <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
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
          {foldable && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={folded ? t("Show more") : t("Show less")}
              aria-expanded={!folded}
              onClick={() => setUnfoldedFor(folded ? title : null)}
            >
              {folded ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronUp className="size-4" />
              )}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("Close")}
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>
        {folded ? (
          <div className="mt-2 text-sm">{summary}</div>
        ) : (
          <>
            {note && (
              <div className="mt-2 hidden text-xs text-muted-foreground sm:block">
                {note}
              </div>
            )}
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              {children}
            </dl>
          </>
        )}
        {footer && (
          <div className="mt-3 flex flex-wrap items-center gap-2">{footer}</div>
        )}
      </div>
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

/** The note under an imprecise position (decision D193): the circle on the map is the
 * uncertainty, and the reader should not take the point for the place. */
export function AccuracyWarning({ accuracyM }: { accuracyM: number }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex items-start gap-1.5 text-xs text-brand-sand"
      role="note"
    >
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
      <span>
        {t(
          "Imprecise: the location is only known to about {{value}} m. The circle on the map shows the uncertainty.",
          { value: Math.round(accuracyM) },
        )}
      </span>
    </div>
  );
}

/** The accuracy as an amber badge; the full sentence sits in its title (decision D193). */
export function AccuracyBadge({ accuracyM }: { accuracyM: number }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-brand-sand/20 px-2 py-0.5 text-xs text-brand-sand"
      title={t(
        "Imprecise: the location is only known to about {{value}} m. The circle on the map shows the uncertainty.",
        { value: Math.round(accuracyM) },
      )}
    >
      <AlertTriangle className="size-3" />
      {t("±{{value}} m", { value: Math.round(accuracyM) })}
    </span>
  );
}

/** The folded state of an entity or device panel on a phone: seen, position (with the
 * accuracy as a badge when it is worth a warning) and battery, on one wrapping line. */
export function PanelSummary({
  lastSeenAt,
  positionTime,
  positionKind,
  accuracy,
  batteryVoltage,
  batteryPercent,
  batteryType,
  batteryProject,
  batteryDevice,
  healthLevel,
  lastMovementAt,
  activity,
  now,
}: {
  lastSeenAt: string | null | undefined;
  positionTime: string | null | undefined;
  positionKind?: string | null;
  accuracy?: number | null;
  batteryVoltage: number | null | undefined;
  /** The share of charge and the chemistry it was read against (decision D248). */
  batteryPercent?: number | null;
  batteryType?: string | null;
  /** Where the battery trend reads from: the project and the device (Tim, 2026-09-14). */
  batteryProject?: string;
  batteryDevice?: string | null;
  healthLevel: string | null | undefined;
  /** Movement from the accelerometer (Tim, 2026-09-14): shown when the device reports it. */
  lastMovementAt?: string | null;
  activity?: number | null;
  now: number;
}) {
  const { t } = useTranslation();
  // the battery and movement trends unfold inside the panel (Tim, 2026-09-14), folded again
  // per object
  const [trendOpen, setTrendOpen] = useState(false);
  const [movementOpen, setMovementOpen] = useState(false);
  const hasMovement = activity !== undefined && activity !== null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span title={formatTime(lastSeenAt)}>
        {t("Seen {{ago}}", { ago: formatAgo(lastSeenAt, now) })}
      </span>
      {positionTime && (
        <span
          title={
            positionKindExplanation(positionKind, t) ?? formatTime(positionTime)
          }
        >
          {isDeviceFix(positionKind)
            ? t("Fix {{ago}}", { ago: formatAgo(positionTime, now) })
            : t("{{kind}} {{ago}}", {
                kind: positionKindLabel(positionKind, t, true),
                ago: formatAgo(positionTime, now),
              })}
        </span>
      )}
      {positionTime && imprecise(accuracy) && (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-brand-sand/20 px-2 py-0.5 text-xs text-brand-sand"
          title={t(
            "Imprecise: the location is only known to about {{value}} m. The circle on the map shows the uncertainty.",
            { value: Math.round(accuracy as number) },
          )}
        >
          <AlertTriangle className="size-3" />
          {t("±{{value}} m", { value: Math.round(accuracy as number) })}
        </span>
      )}
      {batteryVoltage != null && (
        <span className={batteryClass(healthLevel)}>
          {batteryProject ? (
            <BatteryValue
              deviceId={batteryDevice}
              voltage={batteryVoltage}
              percent={batteryPercent}
              batteryType={batteryType}
              open={trendOpen}
              onToggle={() => setTrendOpen((o) => !o)}
            />
          ) : (
            `${batteryVoltage.toFixed(2)} V`
          )}
        </span>
      )}
      {batteryVoltage != null &&
        trendOpen &&
        batteryProject &&
        batteryDevice && (
          <div className="basis-full rounded-md border bg-muted/30 p-2">
            <BatteryTrend
              projectId={batteryProject}
              deviceId={batteryDevice}
              until={lastSeenAt}
            />
          </div>
        )}
      {hasMovement && (
        <span className={batteryClass(movementLevel(lastMovementAt, now))}>
          <MovementValue
            deviceId={batteryProject ? batteryDevice : null}
            lastMovementAt={lastMovementAt}
            now={now}
            open={movementOpen}
            onToggle={() => setMovementOpen((o) => !o)}
          />
        </span>
      )}
      {hasMovement && movementOpen && batteryProject && batteryDevice && (
        <div className="basis-full rounded-md border bg-muted/30 p-2">
          <MovementTrend
            projectId={batteryProject}
            deviceId={batteryDevice}
            until={lastSeenAt}
          />
        </div>
      )}
    </div>
  );
}

/** The battery, last status and last seen rows shared by entities and devices. */
function HealthRows({
  lastSeenAt,
  positionTime,
  positionKind,
  accuracy,
  batteryVoltage,
  batteryPercent,
  batteryType,
  batteryProject,
  batteryDevice,
  healthLevel,
  lastStatusAt,
  lastMovementAt,
  activity,
  uptime,
  lastResetAt,
  heardByName,
  heardByTo,
  contacts,
  lastContactAt,
  contactsTo,
  now,
  onOpenPosition,
  onOpenState,
}: {
  lastSeenAt: string | null | undefined;
  positionTime: string | null | undefined;
  positionKind?: string | null;
  /** Accuracy in metres of the position shown; above the threshold the row warns (D193). */
  accuracy?: number | null;
  batteryVoltage: number | null | undefined;
  /** The share of charge and the chemistry it was read against (decision D248). */
  batteryPercent?: number | null;
  batteryType?: string | null;
  /** Where the battery trend reads from: the project and the device (Tim, 2026-09-14). */
  batteryProject?: string;
  batteryDevice?: string | null;
  healthLevel: string | null | undefined;
  lastStatusAt: string | null | undefined;
  /** Movement from the accelerometer (Tim, 2026-09-14): shown when the device reports it. */
  lastMovementAt?: string | null;
  activity?: number | null;
  /** The uptime in seconds and the last reboot, when the device reports an uptime. */
  uptime?: number | null;
  lastResetAt?: string | null;
  /** Bluetooth sightings of the last 24 hours, when the device reports scans at all, and where
   * the row leads (Tim, 2026-09-18: a count on the panel says whether it is hearing anything). */
  /** The device that heard this one, when its position came from a sighting (D258). */
  heardByName?: string | null;
  heardByTo?: string;
  contacts?: number | null;
  lastContactAt?: string | null;
  contactsTo?: string;
  now: number;
  /** Opens the fix of that moment, the panel a track point opens (Tim, 2026-09-13). */
  onOpenPosition?: () => void;
  /** Opens the device's last status with everything it reported (Tim, 2026-09-13). */
  onOpenState?: () => void;
}) {
  const { t } = useTranslation();
  // the battery and movement trends unfold inside the panel (Tim, 2026-09-14), folded again
  // per object
  const [trendOpen, setTrendOpen] = useState(false);
  const [movementOpen, setMovementOpen] = useState(false);
  const [uptimeOpen, setUptimeOpen] = useState(false);
  const [contactsOpen, setContactsOpen] = useState(false);
  const hasMovement = activity !== undefined && activity !== null;
  const rebooted =
    lastResetAt != null && now - Date.parse(lastResetAt) < 24 * 3_600_000;
  // on a phone the rows stay short (Tim, 2026-09-14): the accuracy as a badge with its
  // sentence behind a tap, and "estimate" for the position's kind
  const phone = useIsPhone();
  return (
    <>
      <PanelRow label={t("Last seen")} title={formatTime(lastSeenAt)}>
        {formatAgo(lastSeenAt, now)}
      </PanelRow>
      <PanelRow label={t("Position")}>
        {positionTime && onOpenPosition ? (
          <button
            type="button"
            className="underline underline-offset-2 hover:text-primary"
            title={t("Show this fix and the measurements of that moment")}
            onClick={onOpenPosition}
          >
            {formatTime(positionTime)}
          </button>
        ) : positionTime ? (
          formatTime(positionTime)
        ) : (
          t("none yet")
        )}
        {positionTime && !isDeviceFix(positionKind) && (
          // a position that is not the device's own fix says so here, or it reads as one and a
          // reader draws the wrong conclusion from it (Tim, 2026-09-18)
          <span
            className="text-muted-foreground"
            title={positionKindExplanation(positionKind, t)}
          >
            {" "}
            · {positionKindLabel(positionKind, t, phone)}
          </span>
        )}
        {positionTime &&
          accuracy != null &&
          !(phone && imprecise(accuracy)) && (
            <span className="text-muted-foreground">
              {" "}
              · {t("±{{value}} m", { value: Math.round(accuracy) })}
            </span>
          )}
        {positionTime && phone && imprecise(accuracy) && (
          <>
            {" "}
            <AccuracyBadge accuracyM={accuracy as number} />
          </>
        )}
        {positionTime && !phone && imprecise(accuracy) && (
          <AccuracyWarning accuracyM={accuracy as number} />
        )}
      </PanelRow>
      {heardByName && (
        // the reader is the point of a proximity position: a tag is where it is because a
        // named device heard it, and a person reading that wants to go to that device
        // (Tim, 2026-09-18)
        <PanelRow label={t("Heard by")}>
          {heardByTo ? (
            <Link className="underline" to={heardByTo}>
              {heardByName}
            </Link>
          ) : (
            heardByName
          )}
        </PanelRow>
      )}
      {batteryVoltage != null && (
        <PanelRow label={t("Battery")} className={batteryClass(healthLevel)}>
          {batteryProject ? (
            <BatteryValue
              deviceId={batteryDevice}
              voltage={batteryVoltage}
              percent={batteryPercent}
              batteryType={batteryType}
              open={trendOpen}
              onToggle={() => setTrendOpen((o) => !o)}
            />
          ) : (
            `${batteryVoltage.toFixed(2)} V`
          )}
        </PanelRow>
      )}
      {batteryVoltage != null &&
        trendOpen &&
        batteryProject &&
        batteryDevice && (
          <div className="col-span-2 rounded-md border bg-muted/30 p-2">
            <BatteryTrend
              projectId={batteryProject}
              deviceId={batteryDevice}
              until={lastSeenAt}
            />
          </div>
        )}
      {hasMovement && (
        <PanelRow
          label={t("Movement")}
          className={batteryClass(movementLevel(lastMovementAt, now))}
          title={lastMovementAt ? formatTime(lastMovementAt) : undefined}
        >
          <MovementValue
            deviceId={batteryProject ? batteryDevice : null}
            lastMovementAt={lastMovementAt}
            now={now}
            open={movementOpen}
            onToggle={() => setMovementOpen((o) => !o)}
          />
        </PanelRow>
      )}
      {hasMovement && movementOpen && batteryProject && batteryDevice && (
        <div className="col-span-2 rounded-md border bg-muted/30 p-2">
          <MovementTrend
            projectId={batteryProject}
            deviceId={batteryDevice}
            until={lastSeenAt}
          />
        </div>
      )}
      {uptime != null && (
        <PanelRow
          label={t("Uptime")}
          className={rebooted ? "text-brand-sand" : ""}
          title={
            lastResetAt
              ? t("Last reboot {{when}}", { when: formatTime(lastResetAt) })
              : undefined
          }
        >
          <UptimeValue
            deviceId={batteryProject ? batteryDevice : null}
            uptimeSeconds={uptime}
            lastResetAt={lastResetAt}
            now={now}
            open={uptimeOpen}
            onToggle={() => setUptimeOpen((o) => !o)}
          />
        </PanelRow>
      )}
      {uptime != null && uptimeOpen && batteryProject && batteryDevice && (
        <div className="col-span-2 rounded-md border bg-muted/30 p-2">
          <UptimeTrend
            projectId={batteryProject}
            deviceId={batteryDevice}
            until={lastSeenAt}
          />
        </div>
      )}
      {contacts != null && (
        <PanelRow
          label={t("Contacts")}
          title={
            lastContactAt
              ? t("Newest sighting {{when}}", {
                  when: formatTime(lastContactAt),
                })
              : undefined
          }
        >
          {batteryProject && batteryDevice ? (
            <button
              type="button"
              className="underline underline-offset-2 hover:text-primary"
              title={
                contactsOpen
                  ? t("Hide how much it hears")
                  : t("Show how much it hears")
              }
              aria-expanded={contactsOpen}
              onClick={() => setContactsOpen((o) => !o)}
            >
              {t("{{count}} in 24 h", { count: contacts })}
            </button>
          ) : contactsTo ? (
            <Link className="underline" to={contactsTo}>
              {t("{{count}} in 24 h", { count: contacts })}
            </Link>
          ) : (
            t("{{count}} in 24 h", { count: contacts })
          )}
          {lastContactAt && (
            <span className="text-muted-foreground">
              {" "}
              · {formatAgo(lastContactAt, now)}
            </span>
          )}
        </PanelRow>
      )}
      {contacts != null && contactsOpen && batteryProject && batteryDevice && (
        <div className="col-span-2 space-y-1 rounded-md border bg-muted/30 p-2">
          <ContactsTrend
            projectId={batteryProject}
            deviceId={batteryDevice}
            until={lastSeenAt}
          />
          {contactsTo && (
            <Link
              className="block text-xs underline text-muted-foreground"
              to={contactsTo}
            >
              {t("Who it heard")}
            </Link>
          )}
        </div>
      )}
      {lastStatusAt && (
        <PanelRow label={t("Last status")} title={formatTime(lastStatusAt)}>
          {onOpenState ? (
            <button
              type="button"
              className="underline underline-offset-2 hover:text-primary"
              title={t(
                "Show everything the device reported in its last status",
              )}
              onClick={onOpenState}
            >
              {formatAgo(lastStatusAt, now)}
            </button>
          ) : (
            formatAgo(lastStatusAt, now)
          )}
        </PanelRow>
      )}
    </>
  );
}

/** The track toggle of a panel: the same icon button as the layers panel's rows, with the
 * count of points beside it. */
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
        size="icon"
        className="size-8"
        aria-pressed={on}
        aria-label={on ? t("Hide the track") : t("Show the track")}
        title={
          on
            ? t("Hide the track")
            : t("Show the track, {{length}}", { length: lengthLabel })
        }
        onClick={onToggle}
      >
        <Route className="size-4" />
      </Button>
      {returned != null && total != null && (
        <span className="text-xs text-muted-foreground">
          {t("{{returned}} of {{total}} points", { returned, total })}
        </span>
      )}
    </>
  );
}

/** The heatmap toggle of a panel (decision D138): per entity and device, like the track. */
export function HeatButton({
  on,
  onToggle,
}: {
  on: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Button
      variant={on ? "default" : "outline"}
      size="icon"
      className="size-8"
      aria-pressed={on}
      aria-label={on ? t("Hide the heatmap") : t("Show the heatmap")}
      title={on ? t("Hide the heatmap") : t("Show the heatmap")}
      onClick={onToggle}
    >
      <Flame className="size-4" />
    </Button>
  );
}

/** Whether the map follows the object as new positions arrive (decision D210, Tim,
 * 2026-09-15): on while selected, off after a drag by hand, on again with this button. */
export function FollowButton({
  on,
  onToggle,
}: {
  on: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Button
      variant={on ? "default" : "outline"}
      size="icon"
      className="size-8"
      aria-pressed={on}
      aria-label={on ? t("Stop following") : t("Follow as positions arrive")}
      title={
        on
          ? t(
              "Following: the map moves with every new position; a drag stops it",
            )
          : t("Follow: the map moves with every new position")
      }
      onClick={onToggle}
    >
      <Crosshair className="size-4" />
    </Button>
  );
}

/** Copies "latitude, longitude" of a position to the clipboard (Tim, 2026-09-13). */
export function CopyPositionButton({
  position,
}: {
  position: [number, number];
}) {
  const { t } = useTranslation();
  const text = `${position[1].toFixed(6)}, ${position[0].toFixed(6)}`;
  return (
    <Button
      variant="outline"
      size="icon"
      className="size-8"
      aria-label={t("Copy the coordinates")}
      title={t("Copy the coordinates, latitude and longitude")}
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => toast.success(t("Copied {{text}}", { text })))
          .catch(() => toast.error(t("The browser refused the clipboard")));
      }}
    >
      <Copy className="size-4" />
    </Button>
  );
}

export function EntityPanel({
  onOpenPosition,
  onOpenState,
  position,
  props,
  projectId,
  allProjects,
  projectName,
  now,
  wasHidden,
  onClose,
  tracked,
  trackLengthLabel,
  track,
  onToggleTrack,
  heat,
  onToggleHeat,
  following,
  onToggleFollow,
}: {
  props: EntityFeatureProperties;
  projectId: string;
  allProjects: boolean;
  projectName: (id: string | null | undefined) => string;
  now: number;
  /** The entity was hidden in the layers panel and switched on for this visit. */
  wasHidden: boolean;
  onClose: () => void;
  tracked: boolean;
  trackLengthLabel: string;
  track?: { returned_points: number; total_points: number };
  onToggleTrack: () => void;
  heat: boolean;
  onToggleHeat: () => void;
  /** The map follows the object as positions arrive (decision D210). */
  following: boolean;
  onToggleFollow: () => void;
  onOpenPosition?: () => void;
  onOpenState?: () => void;
  /** The newest position, for the copy button. */
  position?: [number, number] | null;
}) {
  const { t } = useTranslation();
  const project = projectFor(projectId, props.project_id);
  // the sightings belong to the device, so the row leads to the device's Data tab
  const contactsHref = props.device_id
    ? `/projects/${project}/devices/${props.device_id}?tab=data`
    : undefined;
  // a sighting names the device that made it; the link opens that device on this same map
  const heardByTo = props.heard_by
    ? `/projects/${project}/map?device=${props.heard_by}&devices=1`
    : undefined;
  return (
    <MapPanel
      title={props.name}
      titleTo={`/projects/${project}/entities/${props.entity_id}`}
      subtitle={
        <>
          {props.entity_type_label ?? props.entity_type}
          {allProjects && props.project_id
            ? ` · ${projectName(props.project_id)}`
            : ""}
        </>
      }
      picture={
        <span className="flex size-9 items-center justify-center rounded-full bg-muted">
          <Icon iconKey={props.icon_key} className="size-5 text-primary" />
        </span>
      }
      note={
        wasHidden
          ? t("Hidden in the layers panel until now; it stays shown.")
          : undefined
      }
      summary={
        <PanelSummary
          lastSeenAt={props.last_seen_at}
          positionTime={props.position_time}
          positionKind={props.position_kind}
          accuracy={props.accuracy_m}
          batteryVoltage={props.battery_voltage}
          batteryPercent={props.battery_percent}
          batteryType={props.battery_type}
          batteryProject={projectFor(projectId, props.project_id)}
          batteryDevice={props.device_id}
          healthLevel={props.health_level}
          lastMovementAt={props.last_movement_at}
          activity={props.activity}
          now={now}
        />
      }
      onClose={onClose}
      footer={
        <>
          <TrackButton
            on={tracked}
            lengthLabel={trackLengthLabel}
            returned={track?.returned_points}
            total={track?.total_points}
            onToggle={onToggleTrack}
          />
          <HeatButton on={heat} onToggle={onToggleHeat} />
          <FollowButton on={following} onToggle={onToggleFollow} />
          {position && <CopyPositionButton position={position} />}
        </>
      }
    >
      <HealthRows
        lastSeenAt={props.last_seen_at}
        positionTime={props.position_time}
        positionKind={props.position_kind}
        accuracy={props.accuracy_m}
        onOpenPosition={onOpenPosition}
        onOpenState={onOpenState}
        batteryVoltage={props.battery_voltage}
        batteryPercent={props.battery_percent}
        batteryType={props.battery_type}
        batteryProject={projectFor(projectId, props.project_id)}
        batteryDevice={props.device_id}
        healthLevel={props.health_level}
        lastMovementAt={props.last_movement_at}
        activity={props.activity}
        lastStatusAt={props.last_status_at}
        uptime={props.uptime}
        lastResetAt={props.last_reset_at}
        heardByName={props.heard_by_name}
        heardByTo={heardByTo}
        contacts={props.contacts_24h}
        lastContactAt={props.last_contact_at}
        contactsTo={contactsHref}
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
  onOpenPosition,
  onOpenState,
  position,
  props,
  projectId,
  allProjects,
  projectName,
  now,
  wasHidden,
  onClose,
  tracked,
  trackLengthLabel,
  track,
  onToggleTrack,
  heat,
  onToggleHeat,
  following,
  onToggleFollow,
}: {
  props: DeviceFeatureProperties;
  projectId: string;
  allProjects: boolean;
  projectName: (id: string | null | undefined) => string;
  now: number;
  wasHidden: boolean;
  onClose: () => void;
  tracked: boolean;
  trackLengthLabel: string;
  track?: { returned_points: number; total_points: number };
  onToggleTrack: () => void;
  heat: boolean;
  onToggleHeat: () => void;
  /** The map follows the object as positions arrive (decision D210). */
  following: boolean;
  onToggleFollow: () => void;
  onOpenPosition?: () => void;
  onOpenState?: () => void;
  /** The newest position, for the copy button. */
  position?: [number, number] | null;
}) {
  const { t } = useTranslation();
  const devicePath =
    allProjects && !props.project_id
      ? `/admin/devices/${props.device_id}`
      : `/projects/${projectFor(projectId, props.project_id)}/devices/${props.device_id}`;
  const contactsHref = `${devicePath}?tab=data`;
  const heardByTo = props.heard_by
    ? `/projects/${projectFor(projectId, props.project_id)}/map?device=${props.heard_by}&devices=1`
    : undefined;
  return (
    <MapPanel
      title={props.name}
      titleTo={devicePath}
      subtitle={
        <>
          {props.device_type_label ?? props.device_type}
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
      summary={
        <PanelSummary
          lastSeenAt={props.last_seen_at}
          positionTime={props.position_time}
          positionKind={props.position_kind}
          accuracy={props.accuracy_m}
          batteryVoltage={props.battery_voltage}
          batteryPercent={props.battery_percent}
          batteryType={props.battery_type}
          batteryProject={projectFor(projectId, props.project_id)}
          batteryDevice={props.device_id}
          healthLevel={props.health_level}
          lastMovementAt={props.last_movement_at}
          activity={props.activity}
          now={now}
        />
      }
      onClose={onClose}
      footer={
        <>
          <TrackButton
            on={tracked}
            lengthLabel={trackLengthLabel}
            returned={track?.returned_points}
            total={track?.total_points}
            onToggle={onToggleTrack}
          />
          <HeatButton on={heat} onToggle={onToggleHeat} />
          <FollowButton on={following} onToggle={onToggleFollow} />
          {position && <CopyPositionButton position={position} />}
        </>
      }
    >
      <HealthRows
        lastSeenAt={props.last_seen_at}
        positionTime={props.position_time}
        positionKind={props.position_kind}
        accuracy={props.accuracy_m}
        onOpenPosition={onOpenPosition}
        onOpenState={onOpenState}
        batteryVoltage={props.battery_voltage}
        batteryPercent={props.battery_percent}
        batteryType={props.battery_type}
        batteryProject={projectFor(projectId, props.project_id)}
        batteryDevice={props.device_id}
        healthLevel={props.health_level}
        lastMovementAt={props.last_movement_at}
        activity={props.activity}
        lastStatusAt={props.last_status_at}
        uptime={props.uptime}
        lastResetAt={props.last_reset_at}
        heardByName={props.heard_by_name}
        heardByTo={heardByTo}
        contacts={props.contacts_24h}
        lastContactAt={props.last_contact_at}
        contactsTo={contactsHref}
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
