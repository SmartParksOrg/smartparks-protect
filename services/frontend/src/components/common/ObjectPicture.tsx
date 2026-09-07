import type { ReactNode } from "react";

import { usePicture } from "@/hooks/usePicture";

const SIZES = { xs: "size-6", sm: "size-8", md: "size-10", lg: "size-12" } as const;

/** A round profile picture where the object has one, else the fallback (its type icon). Small
 * on purpose (decision D110): it tells two animals apart without taking the page. */
export function ObjectPicture({
  path,
  updatedAt,
  name,
  size = "sm",
  fallback,
  className = "",
}: {
  path: string | null;
  updatedAt: string | null | undefined;
  name: string;
  size?: keyof typeof SIZES;
  fallback: ReactNode;
  className?: string;
}) {
  const url = usePicture(path, updatedAt);
  if (!url) return <>{fallback}</>;
  return (
    <img
      src={url}
      alt={name}
      className={`${SIZES[size]} shrink-0 rounded-full border object-cover ${className}`}
    />
  );
}
