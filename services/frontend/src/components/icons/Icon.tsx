import { resolveIcon } from "@/components/icons/registry";
import { cn } from "@/lib/utils";

/** Inline SVG from the registry, coloured through `currentColor`. */
export function Icon({ iconKey, className, title }: { iconKey: string | null | undefined; className?: string; title?: string }) {
  const { svg, entry } = resolveIcon(iconKey);
  return (
    <span
      className={cn("inline-flex size-5 shrink-0 [&>svg]:size-full", className)}
      role="img"
      aria-label={title ?? entry.label}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
