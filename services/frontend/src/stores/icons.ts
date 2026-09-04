/**
 * Project icons (architecture 24.6): SVGs a project uploaded under `project.<slug>` keys. The
 * layout loads them for the current project; the Icon component looks here before the built-in
 * registry, so nothing else changes when a type uses a custom icon.
 */
import { create } from "zustand";

import { api } from "@/api/client";
import type { ProjectIcon } from "@/api/types";

interface IconState {
  projectId: string | null;
  icons: Record<string, ProjectIcon>;
  load: (projectId: string | null) => Promise<void>;
}

export const useIconStore = create<IconState>()((set, get) => ({
  projectId: null,
  icons: {},
  async load(projectId) {
    if (projectId === get().projectId) return;
    if (!projectId) { set({ projectId: null, icons: {} }); return; }
    try {
      const list = await api.get<ProjectIcon[]>(`/api/v1/projects/${projectId}/icons`);
      set({ projectId, icons: Object.fromEntries(list.map((i) => [i.key, i])) });
    } catch {
      set({ projectId, icons: {} });
    }
  },
}));

export function projectIcon(key: string | null | undefined): ProjectIcon | undefined {
  return key ? useIconStore.getState().icons[key] : undefined;
}
