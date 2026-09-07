import { useTranslation } from "react-i18next";
import { Settings2, X } from "lucide-react";
import { useState } from "react";

import {
  clampHours,
  describeHours,
  TRACK_MAX_DAYS,
  TRACK_MAX_HOURS,
  TRACK_MIN_HOURS,
  TRACK_QUICK_PICKS,
  type TrackLength,
} from "@/components/map/trackLength";
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
import { useTrackLengthLabel } from "@/components/map/useTrackLengthLabel";

/** What is on the map while tracks are on: how many, how many points, over what length; the
 * gear opens the settings and Clear tracks switches every track off (decision D109). */
export function TracksCard({
  count,
  points,
  length,
  settingsOpen,
  onToggleSettings,
  onClear,
}: {
  count: number;
  points: number;
  length: TrackLength;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const lengthLabel = useTrackLengthLabel(length);
  return (
    <div className="flex h-9 items-center gap-1 rounded-md border bg-card pl-3 pr-1 text-sm shadow-sm">
      <span className="whitespace-nowrap">
        {t("{{count}} tracks", { count })}
        {", "}
        {t("{{count}} points over {{length}}", { count: points, length: lengthLabel })}
      </span>
      <Button
        variant={settingsOpen ? "default" : "ghost"}
        size="icon"
        className="size-7"
        aria-pressed={settingsOpen}
        aria-label={t("Track settings")}
        title={t("Track settings")}
        onClick={onToggleSettings}
      >
        <Settings2 className="size-4" />
      </Button>
      <Button variant="ghost" size="sm" className="h-7" onClick={onClear}>
        {t("Clear tracks")}
      </Button>
    </div>
  );
}

type Unit = "hours" | "days";

/** The track length: since the device was assigned to the entity, or a custom length from one
 * hour to ninety days with a slider in days, a number in hours or days and the quick picks. */
export function TrackSettingsPanel({
  length,
  onChange,
  onClose,
}: {
  length: TrackLength;
  onChange: (next: TrackLength) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const hours = length === "assigned" ? null : length;
  // the custom length stays visible and editable while "since assignment" is chosen, so a
  // person can switch back to what they had; this panel is the only writer of the length while
  // it is open, so its own state never falls behind the URL
  const [customHours, setCustomHours] = useState<number>(hours ?? 24);
  const [unit, setUnit] = useState<Unit>(describeHours(hours ?? 24).unit);
  const [text, setText] = useState<string>(String(describeHours(hours ?? 24).value));

  const setHours = (next: number, nextUnit: Unit = unit) => {
    const clamped = clampHours(next);
    setCustomHours(clamped);
    setUnit(nextUnit);
    setText(String(nextUnit === "days" ? Math.round((clamped / 24) * 100) / 100 : clamped));
    onChange(clamped);
  };
  const commitText = (value: string, nextUnit: Unit) => {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return;
    setHours(nextUnit === "days" ? n * 24 : n, nextUnit);
  };
  const days = Math.min(TRACK_MAX_DAYS, Math.max(1, Math.round(customHours / 24)));

  return (
    <div className="w-80 rounded-md border bg-card p-3 text-sm shadow-md">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">{t("Track settings")}</span>
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
      <div className="mb-1 text-muted-foreground">{t("Track length")}</div>
      <RadioGroup
        value={length === "assigned" ? "assigned" : "custom"}
        onValueChange={(v) => onChange(v === "assigned" ? "assigned" : customHours)}
        className="gap-2"
      >
        <div className="flex items-start gap-2">
          <RadioGroupItem value="assigned" id="track-assigned" className="mt-0.5" />
          <Label htmlFor="track-assigned" className="font-normal leading-snug">
            {t("Since the device was assigned to the entity")}
            <span className="block text-xs text-muted-foreground">
              {t("An entity without a device gets the custom length.")}
            </span>
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="custom" id="track-custom" />
          <Label htmlFor="track-custom" className="font-normal">
            {t("Custom length")}
          </Label>
        </div>
      </RadioGroup>
      <div
        className={`mt-2 space-y-2 ${length === "assigned" ? "opacity-60" : ""}`}
        aria-disabled={length === "assigned"}
      >
        <div className="flex items-center gap-3">
          <Slider
            value={[days]}
            min={1}
            max={TRACK_MAX_DAYS}
            step={1}
            aria-label={t("Track length in days")}
            onValueChange={([d]) => setHours(d * 24, "days")}
            className="flex-1"
          />
          <Input
            type="number"
            inputMode="numeric"
            min={unit === "days" ? 1 : TRACK_MIN_HOURS}
            max={unit === "days" ? TRACK_MAX_DAYS : TRACK_MAX_HOURS}
            value={text}
            aria-label={t("Track length")}
            className="h-8 w-16 px-2"
            onChange={(e) => setText(e.target.value)}
            onBlur={(e) => commitText(e.target.value, unit)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitText((e.target as HTMLInputElement).value, unit);
            }}
          />
          <Select
            value={unit}
            onValueChange={(v) => commitText(text, v as Unit)}
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
        <div className="flex flex-wrap gap-1">
          {TRACK_QUICK_PICKS.map((pick) => (
            <QuickPick
              key={pick}
              hours={pick}
              active={length === pick}
              onClick={() => setHours(pick, describeHours(pick).unit)}
            />
          ))}
        </div>
      </div>
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
