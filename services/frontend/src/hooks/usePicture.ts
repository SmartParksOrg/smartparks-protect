import { useQuery } from "@tanstack/react-query";

import { fetchBlob } from "@/api/client";

// object URLs per version of a picture; a newer version of the same path replaces the old one
const urls = new Map<string, { version: string; url: string }>();

/** The object URL of a profile picture (decision D110), fetched with the bearer token once per
 * version: `updatedAt` is the version, so a changed picture is fetched again and an unchanged
 * one stays in the browser. Null while loading or when the object has no picture. */
export function usePicture(path: string | null, updatedAt: string | null | undefined): string | null {
  const enabled = Boolean(path && updatedAt);
  const query = useQuery({
    queryKey: ["picture", path, updatedAt],
    enabled,
    staleTime: Infinity,
    queryFn: async () => {
      const blob = await fetchBlob(path as string);
      if (!blob) return null;
      const known = urls.get(path as string);
      if (known && known.version !== updatedAt) URL.revokeObjectURL(known.url);
      const url = URL.createObjectURL(blob);
      urls.set(path as string, { version: updatedAt as string, url });
      return url;
    },
  });
  return enabled ? (query.data ?? null) : null;
}
