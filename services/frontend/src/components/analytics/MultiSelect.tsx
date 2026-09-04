import { useTranslation } from "react-i18next";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

/** Searchable multi select on a popover; the trigger shows a count when more than one is chosen. */
export function MultiSelect({ options, value, onChange, placeholder, label, className, maxSelected }: { options: Option[]; value: string[]; onChange: (next: string[]) => void; placeholder: string; label: string; className?: string; maxSelected?: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const chosen = options.filter((o) => value.includes(o.value));
  const text = chosen.length === 0 ? placeholder : chosen.length === 1 ? chosen[0].label : `${chosen.length} ${label}`;

  function toggle(option: string) {
    if (value.includes(option)) onChange(value.filter((v) => v !== option));
    else if (!maxSelected || value.length < maxSelected) onChange([...value, option]);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" aria-expanded={open} aria-label={label} className={cn("justify-between font-normal", className)}>
          <span className={cn("truncate", chosen.length === 0 && "text-muted-foreground")}>{text}</span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command>
          <CommandInput placeholder={`Search ${label}…`} />
          <CommandList>
            <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const selected = value.includes(option.value);
                return (
                  <CommandItem key={option.value} value={`${option.label} ${option.value}`} onSelect={() => toggle(option.value)}>
                    <Check className={cn("mr-2 size-4", selected ? "opacity-100" : "opacity-0")} />
                    <span className="flex-1 truncate">{option.label}</span>
                    {option.hint && <span className="ml-2 text-xs text-muted-foreground">{option.hint}</span>}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
        {value.length > 0 && (
          <div className="border-t p-1">
            <Button variant="ghost" size="sm" className="w-full" onClick={() => onChange([])}>{t("Clear")}</Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
