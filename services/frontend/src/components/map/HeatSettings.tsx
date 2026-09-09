import { useTranslation } from "react-i18next";
import { Settings2, X } from "lucide-react";
import { useState } from "react";

import {
  clampRadius,
  HEAT_MAX_RADIUS_M,
  HEAT_MAX_SENSITIVITY,
  HEAT_MIN_RADIUS_M,
  HEAT_MIN_SENSITIVITY,
  type HeatScope,
  type HeatSettings,
  sensitivityLabel,
} from "@/components/map/heat";
import {
  clampHours,
  describeHours,
  TRACK_MAX_DAYS,
  TRACK_MAX_HOURS,
  TRACK_MIN_HOURS,
  TRACK_QUICK_PICKS,
} from "@/components/map/trackLength";
import { useTrackLengthLabel } from "@/components/map/useTrackLengthLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

/** What the heatmap covers while it is on: how many points over what length, the gear for
 * the settings and a way to switch it off (decision D138, the Tracks card's twin). */
export function HeatCard({
  points,
  capped,
  devicesScanned,
  devicesTotal,
  hours,
  loading,
  settingsOpen,
  onToggleSettings,
  onClear,
}: {
  points: number;
  /** More positions were in view than the cap. */
  capped: boolean;
  /** The read stops at a number of devices, most recently seen first. */
  devicesScanned: number;
  devicesTotal: number;
  hours: number;
  loading: boolean;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const lengthLabel = useTrackLengthLabel(hours);
  return (
    <div className="flex min-h-9 max-w-full items-center gap-1 rounded-md border bg-card py-1 pr-1 pl-3 text-sm shadow-sm">
      <span className="min-w-0 flex-1 leading-tight">
        {t("Heatmap")}
        {", "}
        {loading
          ? t("loading…")
          : capped
            ? t("the newest {{count}} points over {{length}}", {
                count: points,
                length: lengthLabel,
              })
            : t("{{count}} points over {{length}}", {
                count: points,
                length: lengthLabel,
              })}
        {!loading && devicesScanned < devicesTotal
          ? t(", the {{scanned}} most recently seen devices of {{total}}", {
              scanned: devicesScanned,
              total: devicesTotal,
            })
          : ""}
      </span>
      <Button
        variant={settingsOpen ? "default" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={settingsOpen}
        aria-label={t("Heatmap settings")}
        title={t("Heatmap settings")}
        onClick={onToggleSettings}
      >
        <Settings2 className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 shrink-0"
        onClick={onClear}
      >
        {t("Hide heatmap")}
      </Button>
    </div>
  );
}

type Unit = "hours" | "days";

/** The heatmap's radius in metres, its sensitivity and its look-back, with sliders; and what
 * it covers: the shown entities and devices, or the selected one. */
export function HeatSettingsPanel({
  settings,
  scope,
  hasSelection,
  onChange,
  onScopeChange,
  onClose,
}: {
  settings: HeatSettings;
  scope: HeatScope;
  hasSelection: boolean;
  onChange: (next: HeatSettings) => void;
  onScopeChange: (next: HeatScope) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [radiusText, setRadiusText] = useState(String(settings.radius_m));
  const [unit, setUnit] = useState<Unit>(describeHours(settings.hours).unit);
  const [hoursText, setHoursText] = useState(
    String(describeHours(settings.hours).value),
  );
  const setRadius = (metres: number) => {
    const clamped = clampRadius(metres);
    setRadiusText(String(clamped));
    onChange({ ...settings, radius_m: clamped });
  };
  const setHours = (next: number, nextUnit: Unit = unit) => {
    const clamped = clampHours(next);
    setUnit(nextUnit);
    setHoursText(
      String(
        nextUnit === "days" ? Math.round((clamped / 24) * 100) / 100 : clamped,
      ),
    );
    onChange({ ...settings, hours: clamped });
  };
  const commitHours = (value: string, nextUnit: Unit) => {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return;
    setHours(nextUnit === "days" ? n * 24 : n, nextUnit);
  };
  const days = Math.min(
    TRACK_MAX_DAYS,
    Math.max(1, Math.round(settings.hours / 24)),
  );
  // literal keys so the catalogue carries them; `sensitivityLabel` is the untranslated form
  const labelFor = (value: number) =>
    ({
      Low: t("Low"),
      Lower: t("Lower"),
      Medium: t("Medium"),
      Higher: t("Higher"),
      High: t("High"),
    })[sensitivityLabel(value)] ?? sensitivityLabel(value);

  return (
    <div className="w-full rounded-md border bg-card p-3 text-sm shadow-md">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">{t("Heatmap settings")}</span>
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
      <div className="mb-1 flex items-center justify-between text-muted-foreground">
        <span>{t("Radius")}</span>
        <span>{t("{{value}} m", { value: settings.radius_m })}</span>
      </div>
      <div className="mb-3 flex items-center gap-3">
        <Slider
          value={[settings.radius_m]}
          min={HEAT_MIN_RADIUS_M}
          max={HEAT_MAX_RADIUS_M}
          step={10}
          aria-label={t("Radius in metres")}
          onValueChange={([m]) => setRadius(m)}
          className="flex-1"
        />
        <Input
          type="number"
          inputMode="numeric"
          min={HEAT_MIN_RADIUS_M}
          max={HEAT_MAX_RADIUS_M}
          value={radiusText}
          aria-label={t("Radius in metres")}
          className="h-8 w-20 px-2"
          onChange={(e) => setRadiusText(e.target.value)}
          onBlur={(e) => setRadius(Number(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === "Enter")
              setRadius(Number((e.target as HTMLInputElement).value));
          }}
        />
      </div>
      <div className="mb-1 flex items-center justify-between text-muted-foreground">
        <span>{t("Sensitivity")}</span>
        <span>{labelFor(settings.sensitivity)}</span>
      </div>
      <div className="mb-3 flex items-center gap-3">
        <span className="text-xs text-muted-foreground">{t("Low")}</span>
        <Slider
          value={[settings.sensitivity]}
          min={HEAT_MIN_SENSITIVITY}
          max={HEAT_MAX_SENSITIVITY}
          step={1}
          aria-label={t("Sensitivity")}
          onValueChange={([s]) => onChange({ ...settings, sensitivity: s })}
          className="flex-1"
        />
        <span className="text-xs text-muted-foreground">{t("High")}</span>
      </div>
      <div className="mb-1 text-muted-foreground">{t("Look back")}</div>
      <div className="mb-2 flex items-center gap-3">
        <Slider
          value={[days]}
          min={1}
          max={TRACK_MAX_DAYS}
          step={1}
          aria-label={t("Look back in days")}
          onValueChange={([d]) => setHours(d * 24, "days")}
          className="flex-1"
        />
        <Input
          type="number"
          inputMode="numeric"
          min={unit === "days" ? 1 : TRACK_MIN_HOURS}
          max={unit === "days" ? TRACK_MAX_DAYS : TRACK_MAX_HOURS}
          value={hoursText}
          aria-label={t("Look back")}
          className="h-8 w-16 px-2"
          onChange={(e) => setHoursText(e.target.value)}
          onBlur={(e) => commitHours(e.target.value, unit)}
          onKeyDown={(e) => {
            if (e.key === "Enter")
              commitHours((e.target as HTMLInputElement).value, unit);
          }}
        />
        <Select
          value={unit}
          onValueChange={(v) => commitHours(hoursText, v as Unit)}
        >
          <SelectTrigger className="h-8 w-24" aria-label={t("Unit")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hours">{t("hours")}</SelectItem>
            <SelectItem value="days">{t("days")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="mb-3 flex flex-wrap gap-1">
        {TRACK_QUICK_PICKS.map((pick) => (
          <QuickPick
            key={pick}
            hours={pick}
            active={settings.hours === pick}
            onClick={() => setHours(pick, describeHours(pick).unit)}
          />
        ))}
      </div>
      <div className="mb-1 text-muted-foreground">{t("Covers")}</div>
      <RadioGroup
        value={scope}
        onValueChange={(v) => onScopeChange(v as HeatScope)}
        className="gap-1.5"
      >
        <div className="flex items-center gap-2">
          <RadioGroupItem value="shown" id="heat-shown" />
          <Label htmlFor="heat-shown" className="font-normal">
            {t("The shown entities and devices")}
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem
            value="selected"
            id="heat-selected"
            disabled={!hasSelection}
          />
          <Label
            htmlFor="heat-selected"
            className={`font-normal ${hasSelection ? "" : "opacity-60"}`}
          >
            {t("The selected entity or device")}
          </Label>
        </div>
      </RadioGroup>
    </div>
  );
}

function QuickPick({
  hours,
  active,
  onClick,
}: {
  hours: number;
  active: boolean;
  onClick: () => void;
}) {
  const label = useTrackLengthLabel(hours);
  return (
    <Button
      variant={active ? "default" : "outline"}
      size="sm"
      className="h-7 px-2 text-xs"
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
    </Button>
  );
}
