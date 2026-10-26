import { useTranslation } from "react-i18next";
import { Pencil } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { Link } from "react-router";

import type { DeviceAssignments, EntityTimelineRow, ProjectTimelineRow } from "@/api/types";
import { type BoundaryTarget, type NamedCounterpart } from "@/components/devices/BoundaryDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { counterpartsOf, sharedBoundaries, type Edge, type Kind } from "@/lib/assignments";
import { formatAgo, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type AnyRow = ProjectTimelineRow | EntityTimelineRow;

/** The device's assignments as two plain lists (decisions D355 to D358; the timeline and
 * the Transfers card went at Tim's word on 2026-10-26): the project rows and the entity rows,
 * the current one first, each its name and its dates with Edit for whoever may move them. A
 * job shows only while it runs or failed, and a row that was corrected says by whom. The
 * assignment actions (assign, move, release) sit in the cards' headers. */
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
  const shared = useMemo(
    () => (timeline ? sharedBoundaries(timeline.project_assignments, timeline.entity_assignments) : []),
    [timeline],
  );
  if (!timeline) return <div className="text-sm text-muted-foreground">{t("Loading assignments…")}</div>;
  const projects = newestFirst(timeline.project_assignments);
  const entities = newestFirst(timeline.entity_assignments);
  const projectName = (a: ProjectTimelineRow) => a.project_name ?? a.project_id.slice(0, 8);
  const entityName = (a: EntityTimelineRow) => a.entity_name ?? a.entity_id.slice(0, 8);
  const nameOf = (kind: Kind, id: string): string => {
    if (kind === "project") {
      const row = projects.find((r) => r.id === id);
      return row ? projectName(row) : id.slice(0, 8);
    }
    const row = entities.find((r) => r.id === id);
    return row ? entityName(row) : id.slice(0, 8);
  };
  const targetFor = (kind: Kind, row: AnyRow, name: string): BoundaryTarget => {
    const parts = counterpartsOf(shared, kind, row.id);
    const named = (edge: Edge): NamedCounterpart | undefined => {
      const c = parts[edge];
      return c ? { ...c, name: nameOf(c.kind, c.assignmentId) } : undefined;
    };
    return {
      kind,
      assignmentId: row.id,
      name,
      validFrom: row.valid_from,
      validTo: row.valid_to,
      shared: { start: named("start"), end: named("end") },
    };
  };
  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>{t("Project")}</CardTitle>
          {projectActions}
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {projects.length === 0 && (
            <div className="text-muted-foreground">{t("Not assigned to a project.")}</div>
          )}
          {projects.map((a) => (
            <Row
              key={a.id}
              name={projectName(a)}
              href={`/projects/${a.project_id}/devices/${deviceId}`}
              row={a}
              now={now}
              onEdit={timeline.can_edit_project ? () => onEdit(targetFor("project", a, projectName(a))) : undefined}
            />
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>{t("Entity")}</CardTitle>
          {entityActions}
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {entities.length === 0 && (
            <div className="text-muted-foreground">
              {deviceProjectId ? t("Not assigned to an entity.") : t("Not assigned to an entity; Assign to entity asks for the project first.")}
            </div>
          )}
          {entities.map((a) => (
            <Row
              key={a.id}
              name={entityName(a)}
              href={entityLink(a)}
              row={a}
              now={now}
              onEdit={timeline.can_edit_entity ? () => onEdit(targetFor("entity", a, entityName(a))) : undefined}
            />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function newestFirst<T extends { valid_from: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => new Date(b.valid_from).getTime() - new Date(a.valid_from).getTime());
}

function Row({ name, href, row, now, onEdit }: {
  name: string;
  href: string | null;
  row: AnyRow;
  now: Date;
  onEdit?: () => void;
}) {
  const { t } = useTranslation();
  const current = row.valid_to === null;
  const job = row.attribution_job;
  const change = row.last_change;
  return (
    <div className={cn("rounded-md border p-2", current && "border-primary")}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 truncate font-medium">
          {href ? <Link className="underline" to={href}>{name}</Link> : name}
          {current && <span className="ml-2 text-xs font-normal text-muted-foreground">{t("current")}</span>}
        </div>
        {onEdit && (
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <Pencil className="size-3.5" /> {t("Edit")}
          </Button>
        )}
      </div>
      <div className="text-muted-foreground">
        {row.valid_to
          ? t("{{from}} to {{to}}", { from: formatTime(row.valid_from), to: formatTime(row.valid_to) })
          : t("since {{from}}", { from: formatTime(row.valid_from) })}
      </div>
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
