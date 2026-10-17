import { usePreference } from "@/hooks/usePreference";

export type LogFilesView = "list" | "tiles";

/** The files explorer's view, list or tiles, remembered per person (Tim, 2026-10-16). */
export function useLogFilesView(): [LogFilesView, (view: LogFilesView) => void] {
  return usePreference<LogFilesView>("log_files_view", "list");
}
