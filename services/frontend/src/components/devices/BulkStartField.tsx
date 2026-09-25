import { useTranslation } from "react-i18next";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { startOfDayIso } from "@/lib/format";

/** The start the API takes for a selection of devices: each device's first data, the moment
 * it joined its project, now, or an instant. A date is the start of that day in the project's
 * timezone. */
export type BulkStart = "first_data" | "joined" | "now" | string;

/** The start choice for a bulk assignment or a move (decisions D292, D294), the bulk
 * counterpart of `AssignmentStartField`: the moments are resolved per device on the server,
 * so the field offers the choice and no per-device detail. */
export function BulkStartField({
  value,
  onChange,
  timeZone,
  joined = true,
  idPrefix = "bulk-start",
}: {
  value: BulkStart;
  onChange: (next: BulkStart) => void;
  timeZone: string;
  /** Offer "since it joined its project" (a move); an assignment of a device without one does not. */
  joined?: boolean;
  idPrefix?: string;
}) {
  const { t } = useTranslation();
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const isDate = !["first_data", "joined", "now"].includes(value);
  const option = (key: BulkStart, label: string, detail?: string) => (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="radio"
        name={`${idPrefix}-choice`}
        className="mt-1 accent-primary"
        checked={value === key}
        onChange={() => onChange(key)}
      />
      <span>
        {label}
        {detail ? <span className="block text-xs text-muted-foreground">{detail}</span> : null}
      </span>
    </label>
  );
  return (
    <div className="space-y-2">
      {option("first_data", t("Since each device's first data"), t("its earliest record, sighting or log file"))}
      {joined && option("joined", t("Since it joined its current project"))}
      {option("now", t("From now"))}
      <div className="flex items-start gap-2 text-sm">
        <input
          type="radio"
          name={`${idPrefix}-choice`}
          className="mt-1 accent-primary"
          checked={isDate}
          onChange={() => onChange(startOfDayIso(date, timeZone))}
          aria-label={t("On a date")}
        />
        <span className="flex flex-wrap items-center gap-2">
          {t("On a date")}{" "}
          <Input
            type="date"
            className="h-8 w-40"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              if (e.target.value) onChange(startOfDayIso(e.target.value, timeZone));
            }}
            aria-label={t("Start date")}
          />
          <span className="text-xs text-muted-foreground">{t("start of the day, {{zone}}", { zone: timeZone })}</span>
        </span>
      </div>
    </div>
  );
}
