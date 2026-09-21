/**
 * Which project's map this page session last opened (Tim, 2026-09-21).
 *
 * Choosing another project fits the map to what that project's enabled layers hold, since
 * landing on the last project's corner of the world tells nobody anything. Coming back to the
 * map within the same project, or reloading the page, opens where the person left it, which is
 * what the `map_view` preference is for (2026-09-20).
 *
 * Module state on purpose: it lives as long as the loaded page and dies with it, which is
 * exactly what makes a reload count as coming back rather than as a switch.
 */
let lastProject: string | null = null;

/** Whether this project is a different one from the one this page session last opened. */
export function isProjectSwitch(projectId: string): boolean {
  return lastProject !== null && lastProject !== projectId;
}

/** Remember the project whose map is being opened now. */
export function rememberProject(projectId: string): void {
  lastProject = projectId;
}

/** Forget it, as a fresh page load would. For tests. */
export function forgetProjects(): void {
  lastProject = null;
}
