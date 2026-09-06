import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";

import type { DeviceDataSpan } from "@/api/types";
import { Input } from "@/components/ui/input";
import { formatTime, startOfDayIso } from "@/lib/format";

type Choice = "first_data" | "joined" | "now" | "date";

/** When an assignment starts, offered from what the system knows (decision D103): the device's
 * first data, the day it joined the project, now, or a date; a date is the start of that day in
 * the project's timezone. Calls `onChange` with the ISO instant. */
export function AssignmentStartField({
  span,
  joinedAt,
  timeZone,
  onChange,
  idPrefix = "start",
}: {
  span: DeviceDataSpan | undefined;
  joinedAt?: string | null;
  timeZone: string;
  onChange: (iso: string) => void;
  idPrefix?: string;
}) {
  const { t } = useTranslation();
  const firstData = span?.first_data_at ?? null;
  const [choice, setChoice] = useState<Choice>(
    firstData ? "first_data" : "now",
  );
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  // The first choice counts as well: without this a form that never clicked a radio kept its
  // own default ("from now") while the field showed "since the device's first data".
  const reported = useRef(false);
  useEffect(() => {
    if (reported.current) return;
    reported.current = true;
    if (firstData) onChange(firstData);
    else onChange(new Date().toISOString());
  }, [firstData, onChange]);
  const pick = (next: Choice, nextDate = date) => {
    setChoice(next);
    if (next === "first_data" && firstData) onChange(firstData);
    else if (next === "joined" && joinedAt) onChange(joinedAt);
    else if (next === "now") onChange(new Date().toISOString());
    else if (next === "date" && nextDate)
      onChange(startOfDayIso(nextDate, timeZone));
  };
  const option = (
    value: Choice,
    label: string,
    detail?: string | null,
    disabled = false,
  ) => (
    <label
      className={`flex items-start gap-2 text-sm ${disabled ? "text-muted-foreground" : ""}`}
    >
      <input
        type="radio"
        name={`${idPrefix}-choice`}
        className="mt-1 accent-primary"
        checked={choice === value}
        disabled={disabled}
        onChange={() => pick(value)}
      />
      <span>
        {label}
        {detail ? (
          <span className="block text-xs text-muted-foreground">{detail}</span>
        ) : null}
      </span>
    </label>
  );
  return (
    <div className="space-y-2">
      {option(
        "first_data",
        t("Since the device's first data"),
        firstData ? formatTime(firstData) : t("no data yet"),
        !firstData,
      )}
      {joinedAt !== undefined &&
        option(
          "joined",
          t("Since it joined the project"),
          joinedAt ? formatTime(joinedAt) : t("not in a project"),
          !joinedAt,
        )}
      {option("now", t("From now"))}
      <div className="flex items-start gap-2 text-sm">
        <input
          type="radio"
          name={`${idPrefix}-choice`}
          className="mt-1 accent-primary"
          checked={choice === "date"}
          onChange={() => pick("date")}
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
              pick("date", e.target.value);
            }}
            aria-label={t("Start date")}
          />
          <span className="text-xs text-muted-foreground">
            {t("start of the day, {{zone}}", { zone: timeZone })}
          </span>
        </span>
      </div>
    </div>
  );
}
