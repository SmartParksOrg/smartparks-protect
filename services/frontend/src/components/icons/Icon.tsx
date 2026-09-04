import { resolveIcon } from "@/components/icons/registry";
import { cn } from "@/lib/utils";
import { useIconStore } from "@/stores/icons";

/** Inline SVG from the registry, coloured through `currentColor`; a project's own icon
 * (`project.*`, architecture 24.6) takes precedence when the project uploaded one. */
export function Icon({ iconKey, className, title }: { iconKey: string | null | undefined; className?: string; title?: string }) {
  const custom = useIconStore((s) => (iconKey ? s.icons[iconKey] : undefined));
  const resolved = resolveIcon(iconKey);
  const svg = custom?.svg ?? resolved.svg;
  const entry = custom ? { ...resolved.entry, label: custom.label } : resolved.entry;
  return (
    <span
      className={cn("inline-flex size-5 shrink-0 [&>svg]:size-full", className)}
      role="img"
      aria-label={title ?? entry.label}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
