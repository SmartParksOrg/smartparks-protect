/**
 * The live map's feed (decisions D177, D178): the project's newest events with their alert
 * state, and what counts as unread against the person's seen-up-to mark.
 */
export interface FeedItem {
  id: string;
  created_at: string;
  time: string;
  title: string;
  event_type: string;
  severity: string;
  entity_id?: string | null;
  device_id?: string | null;
  alert_id?: string | null;
  alert_status?: string | null;
  geometry?: { type?: string; coordinates?: unknown } | null;
}

/** The newest creation time of the items, or null for none. */
export function newestCreatedAt(items: FeedItem[]): string | null {
  let newest: string | null = null;
  for (const item of items) {
    if (newest === null || item.created_at > newest) newest = item.created_at;
  }
  return newest;
}

/** Whether an item is newer than the mark; with no mark nothing is unread, since the first
 * visit sets the mark at the newest item (decision D178). */
export function isUnread(item: FeedItem, seenUpTo: string | null): boolean {
  return seenUpTo !== null && item.created_at > seenUpTo;
}

/** How many items are unread, capped so the badge stays two digits. */
export function unreadCount(
  items: FeedItem[],
  seenUpTo: string | null,
  cap = 99,
): number {
  return Math.min(items.filter((i) => isUnread(i, seenUpTo)).length, cap);
}

/** The position to fly to, when the event has one. */
export function feedPosition(item: FeedItem): [number, number] | null {
  const g = item.geometry;
  if (!g || g.type !== "Point" || !Array.isArray(g.coordinates)) return null;
  const [lon, lat] = g.coordinates as number[];
  return typeof lon === "number" && typeof lat === "number" ? [lon, lat] : null;
}
