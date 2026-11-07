import { Skeleton } from "@/components/ui/skeleton";
import { useDelayed } from "@/lib/motion";

/** Grey lines where a list is about to land (decision D389), shown only once the read has
 * taken longer than 300 ms, so a fast read never flashes a placeholder. */
export function LoadingLines({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  const slow = useDelayed(true, 300);
  if (!slow) return null;
  return (
    <div className={`space-y-2 ${className}`} role="status" aria-busy="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={i % 2 ? "h-3 w-1/2" : "h-4 w-2/3"} />
      ))}
    </div>
  );
}
