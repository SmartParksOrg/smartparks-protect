import { cn } from "@/lib/utils";

/** A thin bar of a percentage for the jobs a page polls: a log file being decoded, records
 * being given their project and entity. The caller says the numbers next to it. */
export function ProgressBar({ percent, className }: { percent: number; className?: string }) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${value}%` }} />
    </div>
  );
}
