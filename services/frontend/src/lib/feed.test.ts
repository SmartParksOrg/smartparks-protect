import { describe, expect, it } from "vitest";

import {
  type FeedItem,
  feedPosition,
  isUnread,
  newestCreatedAt,
  unreadCount,
} from "@/lib/feed";

const item = (id: string, created: string, extra: Partial<FeedItem> = {}): FeedItem => ({
  id,
  created_at: created,
  time: created,
  title: id,
  event_type: "GEOFENCE_EXIT",
  severity: "high",
  ...extra,
});

describe("feed", () => {
  const items = [
    item("a", "2026-09-12T10:00:00+00:00"),
    item("b", "2026-09-12T11:00:00+00:00"),
    item("c", "2026-09-12T09:00:00+00:00"),
  ];
  it("finds the newest creation time", () => {
    expect(newestCreatedAt(items)).toBe("2026-09-12T11:00:00+00:00");
    expect(newestCreatedAt([])).toBeNull();
  });
  it("counts what is newer than the mark and nothing without a mark", () => {
    expect(unreadCount(items, null)).toBe(0);
    expect(unreadCount(items, "2026-09-12T09:30:00+00:00")).toBe(2);
    expect(unreadCount(items, "2026-09-12T11:00:00+00:00")).toBe(0);
    expect(isUnread(items[1], "2026-09-12T10:00:00+00:00")).toBe(true);
    expect(unreadCount(Array.from({ length: 150 }, (_, i) => item(String(i), "2026-09-13T00:00:00+00:00")), "2026-09-12T00:00:00+00:00")).toBe(99);
  });
  it("reads a point position", () => {
    expect(feedPosition(item("p", "2026-09-12T10:00:00+00:00", { geometry: { type: "Point", coordinates: [31.5, -24.9] } }))).toEqual([31.5, -24.9]);
    expect(feedPosition(item("q", "2026-09-12T10:00:00+00:00", { geometry: null }))).toBeNull();
  });
});
