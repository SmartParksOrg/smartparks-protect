import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const tones: Record<string, string> = {
  ok: "bg-brand-green-light/40 text-foreground border-transparent",
  success: "bg-brand-green-light/40 text-foreground border-transparent",
  processed: "bg-brand-green-light/40 text-foreground border-transparent",
  active: "bg-brand-green-light/40 text-foreground border-transparent",
  online: "bg-brand-green-light/40 text-foreground border-transparent",
  duplicate: "bg-brand-blue/50 text-foreground border-transparent",
  received: "bg-brand-blue/50 text-foreground border-transparent",
  processing: "bg-brand-blue/50 text-foreground border-transparent",
  pending: "bg-brand-blue/50 text-foreground border-transparent",
  unassigned: "bg-brand-sand/50 text-foreground border-transparent",
  degraded: "bg-brand-sand/50 text-foreground border-transparent",
  skipped: "bg-brand-sand/50 text-foreground border-transparent",
  inventory: "bg-muted text-foreground border-transparent",
  unknown: "bg-muted text-foreground border-transparent",
  failed: "bg-destructive/15 text-destructive border-transparent",
  dead_letter: "bg-destructive/15 text-destructive border-transparent",
  offline: "bg-destructive/15 text-destructive border-transparent",
  ignored: "bg-muted text-muted-foreground border-transparent",
};

export function StatusBadge({ value, className }: { value: string | null | undefined; className?: string }) {
  if (!value) return null;
  return <Badge variant="outline" className={cn(tones[value] ?? "", className)}>{value.replace("_", " ")}</Badge>;
}
