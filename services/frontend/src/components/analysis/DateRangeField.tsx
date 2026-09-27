import { useTranslation } from "react-i18next";
import { CalendarDays } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

/** The text of a `datetime-local` input for a day's start or end, in the browser's zone. */
function dayText(date: Date, end: boolean): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${end ? "23:59" : "00:00"}`;
}

function dayOf(value: string | null): Date | undefined {
  if (!value) return undefined;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * One From to To control for a custom period (Tim, 2026-09-27: two separate inputs read as
 * two questions): a button naming the range and a two month calendar under it, where the first
 * click is the start and the second the end. The period covers whole days, from the start of
 * the first to the end of the last, in the browser's zone, which is what the two inputs carried
 * as well.
 */
export function DateRangeField({
  from,
  to,
  onChange,
}: {
  from: string | null;
  to: string | null;
  onChange: (range: { from: string | null; to: string | null }) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const range: DateRange | undefined = dayOf(from)
    ? { from: dayOf(from), to: dayOf(to) }
    : undefined;
  const fmt = (d: Date) =>
    d.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  const text = range?.from
    ? range.to
      ? `${fmt(range.from)} – ${fmt(range.to)}`
      : `${fmt(range.from)} – …`
    : t("Choose the days");
  return (
    <div className="space-y-1">
      <Label className="text-xs">{t("From – To")}</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="h-8 justify-start font-normal"
            aria-label={t("From – To")}
          >
            <CalendarDays className="size-4" />
            {text}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="range"
            numberOfMonths={2}
            selected={range}
            defaultMonth={range?.from}
            onSelect={(next) => {
              onChange({
                from: next?.from ? dayText(next.from, false) : null,
                to: next?.to ? dayText(next.to, true) : null,
              });
              if (next?.from && next?.to) setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
