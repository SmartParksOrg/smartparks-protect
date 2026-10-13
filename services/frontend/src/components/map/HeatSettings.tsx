import { useTranslation } from "react-i18next";
import { Settings2, X } from "lucide-react";
import { useState } from "react";

import {
  clampRadius,
  HEAT_MAX_RADIUS_M,
  HEAT_MAX_SENSITIVITY,
  HEAT_MIN_RADIUS_M,
  HEAT_MIN_SENSITIVITY,
  type HeatSettings,
  sensitivityLabel,
} from "@/components/map/heat";
import { type TrackLength } from "@/components/map/trackLength";
import { LengthSettings } from "@/components/map/TrackSettings";
import { useTrackLengthLabel } from "@/components/map/useTrackLengthLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";

/** What is on the map while heatmaps are on: how many, how many points over what length, the
 * gear for the settings and Clear heatmaps (decision D138, the Tracks card's twin). */
export function HeatCard({
  count,
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
  count: number;
  points: number;
  /** More positions were in view than the cap. */
  capped: boolean;
  /** The read stops at a number of devices, most recently seen first. */
  devicesScanned: number;
  devicesTotal: number;
  hours: TrackLength;
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
        {t("{{count}} heatmaps", { count })}
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
        {t("Clear heatmaps")}
      </Button>
    </div>
  );
}

/** The heatmap's radius in metres, its sensitivity and its look-back (a track length: since
 * the assignment or a custom length), with sliders; one setting for every heatmap on the map. */
export function HeatSettingsPanel({
  settings,
  onChange,
  onClose,
}: {
  settings: HeatSettings;
  onChange: (next: HeatSettings) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [radiusText, setRadiusText] = useState(String(settings.radius_m));
  const setRadius = (metres: number) => {
    const clamped = clampRadius(metres);
    setRadiusText(String(clamped));
    onChange({ ...settings, radius_m: clamped });
  };
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
    <div className="min-h-0 w-full shrink overflow-y-auto rounded-md border bg-card p-3 text-sm shadow-md">
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
      <LengthSettings
        title={t("Look back")}
        titleInDays={t("Look back in days")}
        length={settings.hours}
        onChange={(hours) => onChange({ ...settings, hours })}
      />
    </div>
  );
}
