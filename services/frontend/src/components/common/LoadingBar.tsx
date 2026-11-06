import { cn } from "@/lib/utils";

/** A thin bar that says a read is under way when nobody knows how long it takes (Tim,
 * 2026-11-06: the coverage of a gateway loaded with nothing to look at): the track with a
 * pulsing fill, and the words beside it. Indeterminate on purpose; a job with a known share
 * takes `ProgressBar`. */
export function LoadingBar({ label, className }: { label: string; className?: string }) {
  return (
    <div className={cn("space-y-1", className)} role="status" aria-live="polite">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-full animate-pulse bg-primary/70" />
      </div>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
