/** The trip a person points at in a result's table, so the result map lights it up (vehicle
 * use, Tim, 2026-09-27): a hover follows the pointer, a click pins it and fits the map to it.
 * The key is `<subject id>|<trip number>`, what the segments and markers carry. */
import { create } from "zustand";

interface HighlightState {
  key: string | null;
  pinned: boolean;
  hover: (key: string | null) => void;
  pin: (key: string | null) => void;
}

export const useAnalysisHighlight = create<HighlightState>()((set) => ({
  key: null,
  pinned: false,
  hover: (key) => set((s) => (s.pinned ? s : { key, pinned: false })),
  pin: (key) =>
    set((s) =>
      s.pinned && s.key === key
        ? { key: null, pinned: false }
        : { key, pinned: key !== null },
    ),
}));

export const tripKey = (subjectId: string, trip: number | string): string =>
  `${subjectId}|${trip}`;
