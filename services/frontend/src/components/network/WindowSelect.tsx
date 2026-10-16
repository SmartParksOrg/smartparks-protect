import { useTranslation } from "react-i18next";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { WINDOW_PRESETS, windowLabel } from "@/lib/windows";

/**
 * How far back a traffic or trace list looks (Tim, 2026-10-16: the bare "24" hours field said
 * nothing; a picker with presets does). The value stays `hours` in the URL, so a link with a
 * window outside the presets keeps working and shows as its own entry.
 */
export function WindowSelect({
  hours,
  onChange,
  className = "w-40",
}: {
  hours: number;
  onChange: (hours: number) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const options = WINDOW_PRESETS.some((p) => p.hours === hours)
    ? WINDOW_PRESETS
    : [...WINDOW_PRESETS, { hours, label: "" }].sort((a, b) => a.hours - b.hours);
  return (
    <Select value={String(hours)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger className={className} aria-label={t("Window")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.hours} value={String(o.hours)}>
            {windowLabel(o.hours, t)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
