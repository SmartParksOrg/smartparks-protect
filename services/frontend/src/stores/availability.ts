/**
 * Whether the server answers (decision D329). The API client marks it unavailable on a gateway
 * error or a failed connection and available again on the next answer; the bar in the layout
 * polls the health endpoint meanwhile and refreshes every query when the server is back.
 */
import { create } from "zustand";

import type { UnavailableReason } from "@/lib/availability";

interface AvailabilityState {
  unavailable: { reason: UnavailableReason; since: string } | null;
  markUnavailable: (reason: UnavailableReason) => void;
  markAvailable: () => void;
}

export const useAvailabilityStore = create<AvailabilityState>()((set, get) => ({
  unavailable: null,
  markUnavailable(reason) {
    const current = get().unavailable;
    // "updating" is the more specific word; it is kept over "unreachable" while it lasts
    if (current && (current.reason === reason || current.reason === "updating")) return;
    set({ unavailable: { reason, since: new Date().toISOString() } });
  },
  markAvailable() {
    if (get().unavailable) set({ unavailable: null });
  },
}));
