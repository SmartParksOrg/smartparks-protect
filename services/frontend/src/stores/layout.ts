/** Layout choices of this device: whether the desktop sidebar is hidden. Kept in the browser,
 * not on the server, because a small laptop and a large monitor want different answers. */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface LayoutState {
  sidebarHidden: boolean;
  setSidebarHidden: (hidden: boolean) => void;
}

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      sidebarHidden: false,
      setSidebarHidden: (hidden) => set({ sidebarHidden: hidden }),
    }),
    { name: "protect-layout" },
  ),
);
