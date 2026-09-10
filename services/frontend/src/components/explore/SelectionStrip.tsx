import { useTranslation } from "react-i18next";

import type { Device, Entity, EntityGroup } from "@/api/types";
import { MultiSelect } from "@/components/analytics/MultiSelect";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { browserTimezone, RANGE_PRESETS, TIMEZONES } from "@/lib/analytics";
import { inputValue, type RecordsState } from "@/lib/records";

/** The selection strip of the Explore canvas (decision D151): whose records, over which period,
 * in which timezone. Compact, one row that wraps. */
export function SelectionStrip({
  state,
  entities,
  devices,
  groups,
  oneEntity,
  onChange,
}: {
  state: RecordsState;
  entities: Entity[];
  devices: Device[];
  groups: EntityGroup[];
  oneEntity: boolean;
  onChange: (patch: Partial<RecordsState>) => void;
}) {
  const { t } = useTranslation();
  const groupEntities = (groupId: string) =>
    entities.filter((e) => e.group_id === groupId).map((e) => e.id);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MultiSelect
        options={entities.map((e) => ({ value: e.id, label: e.name }))}
        value={state.entities}
        onChange={(v) => onChange({ entities: v })}
        placeholder={t("Entities")}
        label={t("entities")}
        className="h-8 w-40"
        maxSelected={500}
      />
      <MultiSelect
        options={devices.map((d) => ({ value: d.id, label: d.name }))}
        value={state.devices}
        onChange={(v) => onChange({ devices: v })}
        placeholder={t("Devices")}
        label={t("devices")}
        className="h-8 w-40"
        maxSelected={500}
      />
      {groups.length > 0 && (
        <Select
          value="none"
          onValueChange={(id) =>
            onChange({
              entities: [...new Set([...state.entities, ...groupEntities(id)])],
            })
          }
        >
          <SelectTrigger className="h-8 w-36" aria-label={t("Add a group")}>
            <SelectValue placeholder={t("Add a group")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none" disabled>
              {t("Add a group")}
            </SelectItem>
            {groups.map((g) => (
              <SelectItem key={g.id} value={g.id}>
                {g.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <Select
        value={state.range}
        onValueChange={(v) => onChange({ range: v as RecordsState["range"] })}
      >
        <SelectTrigger className="h-8 w-44" aria-label={t("Period")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(RANGE_PRESETS).map(([k, p]) => (
            <SelectItem key={k} value={k}>
              {p.label}
            </SelectItem>
          ))}
          <SelectItem value="custom">{t("Custom range")}</SelectItem>
          {(oneEntity || state.range === "assignment") && (
            <SelectItem value="assignment">
              {t("Since the device was assigned")}
            </SelectItem>
          )}
        </SelectContent>
      </Select>
      {state.range === "custom" && (
        <>
          <Input
            type="datetime-local"
            aria-label={t("From")}
            className="h-8 w-48"
            value={inputValue(state.from)}
            onChange={(e) => onChange({ from: e.target.value })}
          />
          <Input
            type="datetime-local"
            aria-label={t("To")}
            className="h-8 w-48"
            value={inputValue(state.to)}
            onChange={(e) => onChange({ to: e.target.value })}
          />
        </>
      )}
      <Select
        value={state.timezone}
        onValueChange={(v) => onChange({ timezone: v })}
      >
        <SelectTrigger className="h-8 w-40" aria-label={t("Timezone")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {[...new Set([browserTimezone(), ...TIMEZONES])].map((z) => (
            <SelectItem key={z} value={z}>
              {z}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <label className="flex items-center gap-2 text-sm">
        <Switch
          checked={state.sources === "all"}
          onCheckedChange={(v) => onChange({ sources: v ? "all" : "device" })}
          aria-label={t("Network locations")}
        />
        {t("Network locations")}
      </label>
    </div>
  );
}
