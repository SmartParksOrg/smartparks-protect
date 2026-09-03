import { cn } from "@/lib/utils";

export function JsonView({ value, className }: { value: unknown; className?: string }) {
  return <pre className={cn("max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs", className)}>{JSON.stringify(value, null, 2)}</pre>;
}
