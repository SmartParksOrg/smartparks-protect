import { useTranslation } from "react-i18next";
import { ArrowRightLeft, Pencil } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";

import type { DeviceAssignments, EntityTimelineRow, ProjectTimelineRow } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { type BoundaryTarget } from "@/components/devices/BoundaryDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { axisOf, layOut, sharedBoundaries, type TimelineRow } from "@/lib/assignments";
import { formatAgo, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The device's two timelines side by side on one time axis (decisions D355 to D358): a
 * lane of project assignments and a lane of entity assignments from the first start to now,
 * the current row marked, the attribution job and the last change per row, a pencil on
 * every boundary for whoever may move it, and "Correct both" where a project and an entity
 * boundary share an instant. The assignment actions (assign, move, release) sit in the
 * cards' headers, where the Overview had them before. */
export function AssignmentsTab({
  timeline,
  now,
  deviceId,
  deviceProjectId,
  entityLink,
  projectActions,
  entityActions,
  onEdit,
}: {
  timeline: DeviceAssignments | undefined;
  now: Date;
  deviceId: string;
  deviceProjectId: string | null;
  entityLink: (row: { entity_id: string; valid_from: string }) => string | null;
  projectActions: ReactNode;
  entityActions: ReactNode;
  onEdit: (target: BoundaryTarget) => void;
}) {
  const { t } = useTranslation();
  const [hover, setHover] = useState<string | null>(null);
  const rows: TimelineRow[] = useMemo(
    () => [...(timeline?.project_assignments ?? []), ...(timeline?.entity_assignments ?? [])],
    [timeline],
  );
  const axis = useMemo(() => axisOf(rows, now), [rows, now]);
  const shared = useMemo(
    () => (timeline ? sharedBoundaries(timeline.project_assignments, timeline.entity_assignments) : []),
    [timeline],
  );
  if (!timeline) return <div className="text-sm text-muted-foreground">{t("Loading assignments…")}</div>;
  const projects = axis ? layOut(timeline.project_assignments, axis, now) : [];
  const entities = axis ? layOut(timeline.entity_assignments, axis, now) : [];
  const canProject = timeline.can_edit_project;
  const canEntity = timeline.can_edit_entity;
  return (
    <div className="space-y-4">
      {axis && (
        <Card>
          <CardContent className="space-y-2 pt-4">
            <Lane
              label={t("Project")}
              rows={projects.map((l) => ({ ...l, name: l.row.project_name ?? l.row.project_id.slice(0, 8), href: `/projects/${l.row.project_id}/devices/${deviceId}` }))}
              hover={hover}
              setHover={setHover}
            />
            <Lane
              label={t("Entity")}
              rows={entities.map((l) => ({ ...l, name: l.row.entity_name ?? l.row.entity_id.slice(0, 8), href: entityLink(l.row) }))}
              hover={hover}
              setHover={setHover}
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{formatTime(new Date(axis.start).toISOString())}</span>
              <span>{t("now")}</span>
            </div>
          </CardContent>
        </Card>
      )}
      {shared.length > 0 && (canProject || canEntity) && (
        <Card>
          <CardHeader><CardTitle>{t("Transfers")}</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p className="text-muted-foreground">{t("Where the project and the entity changed at the same moment. Correct both at once when the device really changed hands earlier or later, for example one second after its last uplink in the old project.")}</p>
            {shared.map((b) => (
              <div key={b.instant} className="flex flex-wrap items-center justify-between gap-2">
                <span>{formatTime(b.instant)}</span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!(canProject && canEntity)}
                  title={!(canProject && canEntity) ? t("Needs the right to move both the project and the entity boundary") : undefined}
                  onClick={() =>
                    onEdit({
                      kind: "both",
                      projectAssignmentId: b.projectAssignmentId,
                      projectEdge: b.projectEdge,
                      entityAssignmentId: b.entityAssignmentId,
                      entityEdge: b.entityEdge,
                      current: b.instant,
                    })
                  }
                >
                  <ArrowRightLeft className="size-4" /> {t("Correct both")}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle>{t("Project assignments")}</CardTitle>
            {projectActions}
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {timeline.project_assignments.length === 0 && (
              <div className="text-muted-foreground">{t("Not assigned to a project.")}</div>
            )}
            {timeline.project_assignments.map((a) => (
              <Row
                key={a.id}
                id={a.id}
                name={a.project_name ?? a.project_id.slice(0, 8)}
                href={`/projects/${a.project_id}/devices/${deviceId}`}
                row={a}
                now={now}
                hover={hover}
                setHover={setHover}
                canEdit={canProject}
                onEditStart={() => onEdit({ kind: "project", assignmentId: a.id, edge: "start", current: a.valid_from, name: a.project_name ?? "" })}
                onEditEnd={a.valid_to ? () => onEdit({ kind: "project", assignmentId: a.id, edge: "end", current: a.valid_to!, name: a.project_name ?? "" }) : undefined}
              />
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2">
            <CardTitle>{t("Entity assignments")}</CardTitle>
            {entityActions}
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {timeline.entity_assignments.length === 0 && (
              <div className="text-muted-foreground">
                {deviceProjectId ? t("Not assigned to an entity.") : t("Not assigned to an entity; Assign to entity asks for the project first.")}
              </div>
            )}
            {timeline.entity_assignments.map((a) => (
              <Row
                key={a.id}
                id={a.id}
                name={a.entity_name ?? a.entity_id.slice(0, 8)}
                href={entityLink(a)}
                row={a}
                now={now}
                hover={hover}
                setHover={setHover}
                canEdit={canEntity}
                onEditStart={() => onEdit({ kind: "entity", assignmentId: a.id, edge: "start", current: a.valid_from, name: a.entity_name ?? "" })}
                onEditEnd={a.valid_to ? () => onEdit({ kind: "entity", assignmentId: a.id, edge: "end", current: a.valid_to!, name: a.entity_name ?? "" }) : undefined}
              />
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Lane({ label, rows, hover, setHover }: {
  label: string;
  rows: { row: TimelineRow; left: number; width: number; current: boolean; name: string; href: string | null }[];
  hover: string | null;
  setHover: (id: string | null) => void;
}) {
  return (
    <div className="grid grid-cols-[4rem_1fr] items-center gap-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="relative h-7 rounded bg-muted">
        {rows.map((l) => (
          <div
            key={l.row.id}
            title={`${l.name}: ${formatTime(l.row.valid_from)} – ${l.row.valid_to ? formatTime(l.row.valid_to) : ""}`}
            onMouseEnter={() => setHover(l.row.id)}
            onMouseLeave={() => setHover(null)}
            className={cn(
              "absolute top-0.5 bottom-0.5 overflow-hidden rounded border px-1 text-xs leading-6 whitespace-nowrap",
              l.current ? "border-primary bg-primary/30 font-medium" : "border-brand-green-light bg-brand-green-light/40",
              hover === l.row.id && "ring-2 ring-primary",
            )}
            style={{ left: `${l.left}%`, width: `${l.width}%` }}
          >
            {l.name}
          </div>
        ))}
      </div>
    </div>
  );
}

function Row({ id, name, href, row, now, hover, setHover, canEdit, onEditStart, onEditEnd }: {
  id: string;
  name: string;
  href: string | null;
  row: ProjectTimelineRow | EntityTimelineRow;
  now: Date;
  hover: string | null;
  setHover: (id: string | null) => void;
  canEdit: boolean;
  onEditStart: () => void;
  onEditEnd?: () => void;
}) {
  const { t } = useTranslation();
  const job = row.attribution_job;
  const change = row.last_change;
  return (
    <div
      className={cn("rounded-md border p-2", row.valid_to === null && "border-primary", hover === id && "ring-2 ring-primary")}
      onMouseEnter={() => setHover(id)}
      onMouseLeave={() => setHover(null)}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <div className="font-medium">
          {href ? <Link className="underline" to={href}>{name}</Link> : name}
          {row.valid_to === null && <span className="ml-2 text-xs font-normal text-muted-foreground">{t("current")}</span>}
        </div>
        {job && <StatusBadge value={job.status} />}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-1">
        <span>{formatTime(row.valid_from)}</span>
        {canEdit && (
          <Button type="button" variant="ghost" size="icon" className="size-6" title={t("Move the start")} onClick={onEditStart}>
            <Pencil className="size-3.5" />
          </Button>
        )}
        <span className="text-muted-foreground">{t("to")}</span>
        <span>{row.valid_to ? formatTime(row.valid_to) : t("now")}</span>
        {canEdit && onEditEnd && (
          <Button type="button" variant="ghost" size="icon" className="size-6" title={t("Move the end")} onClick={onEditEnd}>
            <Pencil className="size-3.5" />
          </Button>
        )}
      </div>
      {row.reason && <div className="text-xs text-muted-foreground">{row.reason}</div>}
      {job && job.status !== "complete" && (
        <div className="text-xs text-muted-foreground">
          {job.status === "failed"
            ? t("Attribution failed: {{message}}", { message: job.error_message ?? job.error_code ?? "" })
            : t("{{done}} of {{total}} records given their project and entity", { done: job.records_done, total: job.records_total })}
        </div>
      )}
      {change && (
        <div className="text-xs text-muted-foreground">
          {t("Changed {{ago}} by {{who}}", { ago: formatAgo(change.time, now.getTime()), who: change.user_name ?? t("the system") })}
          {change.reason ? `: ${change.reason}` : ""}
        </div>
      )}
    </div>
  );
}
