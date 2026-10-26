/** The pure part of the Assignments tab (decisions D355 to D358): the lanes of a device's
 * timeline laid out on one time axis, the boundaries a project and an entity row share (the
 * ones "Correct both" moves together), and the wall-clock text of an instant in a timezone
 * for the boundary dialog's picker. */

export interface TimelineRow {
  id: string;
  valid_from: string;
  valid_to: string | null;
}

export interface LaidOut<T extends TimelineRow> {
  row: T;
  /** Percent of the axis from its start. */
  left: number;
  /** Percent of the axis. */
  width: number;
  current: boolean;
}

export interface Axis {
  start: number;
  end: number;
}

/** One axis for both lanes: from the earliest start to now (or the latest end when nothing is
 * open and the newest end lies in the future, which a clock error could make). */
export function axisOf(rows: TimelineRow[], now: Date): Axis | null {
  if (rows.length === 0) return null;
  const starts = rows.map((r) => new Date(r.valid_from).getTime());
  const ends = rows.map((r) =>
    r.valid_to ? new Date(r.valid_to).getTime() : now.getTime(),
  );
  const start = Math.min(...starts);
  const end = Math.max(now.getTime(), ...ends);
  return end > start ? { start, end } : { start, end: start + 1 };
}

export function layOut<T extends TimelineRow>(
  rows: T[],
  axis: Axis,
  now: Date,
): LaidOut<T>[] {
  const span = axis.end - axis.start;
  return rows.map((row) => {
    const from = new Date(row.valid_from).getTime();
    const to = row.valid_to ? new Date(row.valid_to).getTime() : now.getTime();
    const left = ((from - axis.start) / span) * 100;
    // a row of a moment still shows as a sliver
    const width = Math.max(((to - from) / span) * 100, 0.5);
    return { row, left, width, current: row.valid_to === null };
  });
}

export type Edge = "start" | "end";

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
 * both lanes is left out: it is where the device's history begins, not a transfer. */
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
