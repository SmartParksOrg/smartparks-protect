/** One string for one picture version. The API writes the same instant two ways (`Z` from a
 * schema, `+00:00` from the map features), and a version string that differs by notation made
 * the picture hook revoke an object URL another view still showed. */
export function pictureVersion(updatedAt: string | null | undefined): string | null {
  if (!updatedAt) return null;
  const time = Date.parse(updatedAt);
  return Number.isNaN(time) ? updatedAt : new Date(time).toISOString();
}
