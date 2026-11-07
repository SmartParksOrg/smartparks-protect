import { useLiveNow } from "@/hooks/useNow";
import { formatAgo, formatTime } from "@/lib/format";

/** "just now", "23 s ago", "4 min ago": a moment as its distance from now, counting every
 * second while it is under a minute old (decision D387), with the full time as the title. */
export function Ago({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const now = useLiveNow([value]);
  return (
    <span className={className} title={value ? formatTime(value) : undefined}>
      {formatAgo(value, now)}
    </span>
  );
}
