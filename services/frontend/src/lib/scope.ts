/** The all-projects scope (decision D115): the reserved project id `all` in the URL, for
 * server admins. Pages that support it read every project at once; links inside it point at
 * the object's own project. */
export const ALL_PROJECTS = "all";

export const isAllProjects = (projectId: string | undefined | null): boolean =>
  projectId === ALL_PROJECTS;

/** The project to link into for an object seen in a scope: its own in the all scope. */
export function projectFor(
  scopeProjectId: string,
  objectProjectId: string | null | undefined,
): string {
  return isAllProjects(scopeProjectId) && objectProjectId ? objectProjectId : scopeProjectId;
}
