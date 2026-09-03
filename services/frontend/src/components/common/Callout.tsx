import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const styles = {
  info: ["border-brand-blue bg-brand-blue/20", Info],
  success: ["border-brand-green-light bg-brand-green-light/20", CircleCheck],
  warning: ["border-brand-sand bg-brand-sand/20", TriangleAlert],
  error: ["border-destructive/40 bg-destructive/10", CircleAlert],
} as const;

/** Every short status or hint message uses this, never a hand-rolled coloured div. */
export function Callout({ kind = "info", children, className }: { kind?: keyof typeof styles; children: ReactNode; className?: string }) {
  const [style, Icon] = styles[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-sm", style, className)}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
