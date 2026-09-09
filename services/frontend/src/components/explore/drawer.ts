/** The drawer's measures, shared with the page that lays the canvas out above it. */
export const HANDLE = 36;

/** The height the drawer takes on the canvas, for the content above it. */
export function drawerSpace(
  open: boolean,
  height: number,
  phone: boolean,
): number | string {
  if (!open) return HANDLE;
  return phone ? "55%" : height + HANDLE;
}
