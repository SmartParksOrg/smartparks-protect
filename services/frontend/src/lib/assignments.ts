/** The pure part of the Assignments tab (decisions D355 to D358): the boundaries a project
 * row and an entity row share (a transfer that changed both at once, which the edit dialog
 * offers to move together), the counterpart of a row's edge on the other list, and the
 * wall-clock text of an instant in a timezone for the dialog's date fields. */

export interface TimelineRow {
  id: string;
  valid_from: string;
  valid_to: string | null;
}

export type Edge = "start" | "end";
export type Kind = "project" | "entity";

export interface SharedBoundary {
  instant: string;
  projectAssignmentId: string;
  projectEdge: Edge;
  entityAssignmentId: string;
  entityEdge: Edge;
}

function edgesOf(rows: TimelineRow[]): Map<number, { id: string; edge: Edge }> {
  // the row that starts at an instant wins over the one that ends there: moving a start is
  // what a person means by "the boundary", and the end follows as the neighbour
  const out = new Map<number, { id: string; edge: Edge }>();
  for (const row of rows) {
    if (row.valid_to)
      out.set(new Date(row.valid_to).getTime(), { id: row.id, edge: "end" });
  }
  for (const row of rows) {
    out.set(new Date(row.valid_from).getTime(), { id: row.id, edge: "start" });
  }
  return out;
}

/** The instants where a project edge and an entity edge coincide: a transfer that changed
 * both at once, which is corrected as one (the chained correction). The earliest start of
 * both lists is left out: it is where the device's history begins, not a transfer. */
export function sharedBoundaries(
  projects: TimelineRow[],
  entities: TimelineRow[],
): SharedBoundary[] {
  const projectEdges = edgesOf(projects);
  const entityEdges = edgesOf(entities);
  const firstStart = Math.min(
    ...[...projects, ...entities].map((r) => new Date(r.valid_from).getTime()),
  );
  const out: SharedBoundary[] = [];
  for (const [instant, project] of projectEdges) {
    const entity = entityEdges.get(instant);
    if (!entity || instant === firstStart) continue;
    out.push({
      instant: new Date(instant).toISOString(),
      projectAssignmentId: project.id,
      projectEdge: project.edge,
      entityAssignmentId: entity.id,
      entityEdge: entity.edge,
    });
  }
  return out.sort((a, b) => a.instant.localeCompare(b.instant));
}

/** The row of the other kind whose edge sits on the same instant as one of this row's. */
export interface Counterpart {
  kind: Kind;
  assignmentId: string;
  edge: Edge;
}

/** For one row, the counterpart of each of its edges that a row of the other kind shares:
 * what the edit dialog offers to move along with that edge. */
export function counterpartsOf(
  shared: SharedBoundary[],
  kind: Kind,
  assignmentId: string,
): Partial<Record<Edge, Counterpart>> {
  const out: Partial<Record<Edge, Counterpart>> = {};
  for (const b of shared) {
    if (kind === "project" && b.projectAssignmentId === assignmentId)
      out[b.projectEdge] = { kind: "entity", assignmentId: b.entityAssignmentId, edge: b.entityEdge };
    if (kind === "entity" && b.entityAssignmentId === assignmentId)
      out[b.entityEdge] = { kind: "project", assignmentId: b.projectAssignmentId, edge: b.projectEdge };
  }
  return out;
}

function partsOf(date: Date, timeZone: string): Record<string, number> {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const out: Record<string, number> = {};
  for (const p of parts) if (p.type !== "literal") out[p.type] = Number(p.value);
  // "24" never comes with h23, but a broken engine once did
  if (out.hour === 24) out.hour = 0;
  return out;
}

const pad = (n: number, width = 2) => String(n).padStart(width, "0");

/** An instant as the wall-clock text a `datetime-local` input takes, in a timezone:
 * "2026-10-25T16:13:52" for 14:13:52Z in Europe/Amsterdam. */
export function isoToWall(iso: string, timeZone: string): string {
  const p = partsOf(new Date(iso), timeZone);
  return `${pad(p.year, 4)}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/** The instant a wall-clock text names in a timezone, as ISO; null for text that is not a
 * date. Solved by one correction step, as `startOfDayIso` does, which is exact outside the
 * hour a clock change skips or repeats. */
export function wallToIso(wall: string, timeZone: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(wall);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1).map((v) => Number(v ?? 0));
  const guess = Date.UTC(y, mo - 1, d, h, mi, s || 0);
  if (Number.isNaN(guess)) return null;
  const p = partsOf(new Date(guess), timeZone);
  const seen = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return new Date(guess - (seen - guess)).toISOString();
}
