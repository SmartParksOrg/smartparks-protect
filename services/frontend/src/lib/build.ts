/**
 * Whether the page in front of somebody is still the one the server serves (Tim, 2026-09-21).
 *
 * The interface is one bundle loaded once: a tab left open keeps running the code it started
 * with, however often the server is deployed, and nothing on screen says so. That cost an
 * afternoon of "still the same issue" over a bug that had already been fixed. The API's
 * `/api/version` names the commit it was built from, and the frontend is built and deployed
 * from the same one, so a commit that has moved since this tab loaded means the tab is old.
 */

/** What `/api/version` answers. */
export interface ServerBuild {
  version: string;
  commit: string;
}

/**
 * Whether the tab should be reloaded: the server is on another commit than the one it answered
 * when this tab loaded. An unknown commit (a server without `GIT_COMMIT`, a development run)
 * says nothing, and neither does the first answer.
 */
export function buildMoved(
  loaded: ServerBuild | null,
  now: ServerBuild | null | undefined,
): boolean {
  if (!loaded || !now) return false;
  if (!loaded.commit || !now.commit) return false;
  if (loaded.commit === "unknown" || now.commit === "unknown") return false;
  return loaded.commit !== now.commit;
}

/** The build the server reported when this tab first asked. Module state on purpose: it is
 * the age of the loaded bundle, and it dies with the page, which is what a reload does. */
let first: ServerBuild | null = null;

/** Keep the first answer, and say what it was. Later answers are compared against it. */
export function rememberBuild(seen: ServerBuild): ServerBuild {
  if (!first) first = seen;
  return first;
}

/** What the server was on when this tab loaded, or null before the first answer. */
export function loadedBuild(): ServerBuild | null {
  return first;
}

/** Forget it, as a reload would. For tests. */
export function forgetBuild(): void {
  first = null;
}
