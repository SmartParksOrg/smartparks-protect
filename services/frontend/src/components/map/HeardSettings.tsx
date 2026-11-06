import { useTranslation } from "react-i18next";
import { Settings2, X } from "lucide-react";

import { LoadingBar } from "@/components/common/LoadingBar";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { COVERAGE_PERIODS, periodLabel } from "@/lib/coverage";

/** What is on the map while heard positions are on (decision D373, the Tracks card's twin):
 * how many toggles, how many positions over which period, a bar while a read runs, the gear
 * for the settings and Clear. */
export function HeardCard({
  count,
  total,
  points,
  hours,
  loading,
  settingsOpen,
  onToggleSettings,
  onClear,
}: {
  /** Entities, devices and gateways with their heard positions on, plus the view when ticked. */
  count: number;
  total: number;
  points: number;
  hours: number;
  loading: boolean;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const period = periodLabel(hours, t);
  return (
    // shrink-0: the phone's column clips what it cannot fit, and a card of one line must
    // stay whole while the panel below it gives way (Tim, 2026-11-06)
    <div className="flex min-h-9 max-w-full shrink-0 flex-col gap-1 rounded-md border bg-card py-1 pr-1 pl-3 text-sm shadow-sm">
      <div className="flex items-center gap-1">
        <span
          className="min-w-0 flex-1 leading-tight"
          title={t("{{count}} switched on", { count })}
        >
          {points < total
            ? t("the newest {{points}} of {{total}} heard positions, {{period}}", {
                points,
                total,
                period,
              })
            : t("{{count}} heard positions, {{period}}", { count: total, period })}
        </span>
        <Button
          variant={settingsOpen ? "default" : "ghost"}
          size="icon"
          className="size-7"
          aria-pressed={settingsOpen}
          aria-label={t("Heard positions settings")}
          title={t("Heard positions settings")}
          onClick={onToggleSettings}
        >
          <Settings2 className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 shrink-0"
          title={t("Clear heard positions")}
          onClick={onClear}
        >
          <span className="sm:hidden">{t("Clear")}</span>
          <span className="hidden sm:inline">{t("Clear heard positions")}</span>
        </Button>
      </div>
      {loading && <LoadingBar className="pr-2 pb-1" label={t("Loading the heard positions…")} />}
    </div>
  );
}

/** The period, the lines to the gateways and the signal legend: one setting for every heard
 * positions toggle on the map, kept in the layer preference. */
export function HeardSettingsPanel({
  hours,
  lines,
  onChange,
  onClose,
}: {
  hours: number;
  lines: boolean;
  onChange: (next: { hours: number; lines: boolean }) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="min-h-0 w-full shrink overflow-y-auto rounded-md border bg-card p-3 text-sm shadow-md">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">{t("Heard positions settings")}</span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={t("Close")}
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-muted-foreground">{t("Period")}</span>
        <Select
          value={String(hours)}
          onValueChange={(v) => onChange({ hours: Number(v), lines })}
        >
          <SelectTrigger className="h-8 w-32" aria-label={t("Period")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COVERAGE_PERIODS.map((h) => (
              <SelectItem key={h} value={String(h)}>
                {periodLabel(h, t)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <Label htmlFor="heard-lines" className="font-normal text-muted-foreground">
          {t("Lines to the gateways")}
        </Label>
        <Switch
          id="heard-lines"
          checked={lines}
          onCheckedChange={(v) => onChange({ hours, lines: v })}
        />
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        {t(
          "The path every uplink took: a thin line from the heard position to each gateway that received it",
        )}
      </p>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{t("-120 dBm")}</span>
        <span
          className="h-2 flex-1 rounded"
          style={{
            background: "linear-gradient(90deg, #b91c1c, #f59e0b, #a3c14a, #15803d)",
          }}
        />
        <span>{t("-80 dBm")}</span>
      </div>
    </div>
  );
}
