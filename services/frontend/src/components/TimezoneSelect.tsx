import { Check, ChevronsUpDown } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { orderedTimezones, zoneLabel } from "@/lib/timezones";
import { cn } from "@/lib/utils";

/** A searchable timezone picker (Tim, 2026-09-16): every zone the browser knows with its
 * offset beside the name, the browser's zone and the zones in `first` at the top. Compact
 * (`size="sm"`) in the explorer's strip, full width in a form. */
export function TimezoneSelect({
  id,
  value,
  onChange,
  first = [],
  size = "default",
  className,
  disabled,
}: {
  id?: string;
  value: string;
  onChange: (zone: string) => void;
  /** Zones worth a first look, after the browser's own: the project's, other projects'. */
  first?: string[];
  size?: "default" | "sm";
  className?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const zones = useMemo(
    () => (open ? orderedTimezones(first, value) : []),
    [open, first, value],
  );
  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label={t("Timezone")}
          disabled={disabled}
          className={cn(
            "justify-between font-normal",
            size === "sm" ? "h-8 px-2 text-sm" : "w-full",
            className,
          )}
        >
          <span className="truncate">
            {value ? zoneLabel(value) : t("Choose a timezone")}
          </span>
          <ChevronsUpDown
            className="ml-2 size-4 shrink-0 opacity-50"
            aria-hidden
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] min-w-72 p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder={t("Search timezones…")} />
          <CommandList>
            <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>
            <CommandGroup>
              {zones.map((zone) => (
                <CommandItem
                  key={zone}
                  value={zone}
                  onSelect={() => {
                    onChange(zone);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 size-4",
                      zone === value ? "opacity-100" : "opacity-0",
                    )}
                    aria-hidden
                  />
                  <span className="truncate">{zoneLabel(zone)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
