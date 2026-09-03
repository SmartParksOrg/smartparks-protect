/** The selected project. Persisted so a reload opens the same project. */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ProjectState {
  lastProjectId: string | null;
  setLastProjectId: (id: string | null) => void;
}

export const useProjectStore = create<ProjectState>()(
  persist((set) => ({ lastProjectId: null, setLastProjectId: (id) => set({ lastProjectId: id }) }), {
    name: "protect-project",
  }),
);
