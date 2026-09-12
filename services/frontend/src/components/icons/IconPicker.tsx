import { useTranslation } from "react-i18next";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { Icon } from "@/components/icons/Icon";
import { type IconEntry, iconKeys, registry } from "@/components/icons/registry";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const CATEGORIES: IconEntry["category"][] = ["wildlife", "person", "vehicle", "infrastructure", "device", "event"];

/** Searchable choice of a registry icon key, grouped by category: the registry holds a few
 * hundred icons since the vendored set arrived (decision D165), too many for a plain select. The
 * search matches the label, the key and the aliases (a Latin name, a common synonym). */
export function IconPicker({ id, value, onChange, className }: { id?: string; value: string; onChange: (key: string) => void; className?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const labels: Record<IconEntry["category"], string> = {
    wildlife: t("Wildlife"),
    person: t("People"),
    vehicle: t("Vehicles"),
    infrastructure: t("Infrastructure"),
    device: t("Devices"),
    event: t("Events"),
  };
  const chosen = value ? registry[value] : undefined;
  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button id={id} type="button" variant="outline" role="combobox" aria-expanded={open} className={cn("w-full justify-between font-normal", className)}>
          <span className={cn("inline-flex min-w-0 items-center gap-2", !chosen && "text-muted-foreground")}>
            {chosen && <Icon iconKey={value} className="size-4" />}
            <span className="truncate">{chosen ? chosen.label : t("Choose an icon")}</span>
            {chosen && <span className="truncate text-xs text-muted-foreground">{value}</span>}
          </span>
          <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command>
          <CommandInput placeholder={t("Search icons…")} />
          <CommandList>
            <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>
            {CATEGORIES.map((category) => (
              <CommandGroup key={category} heading={labels[category]}>
                {iconKeys.filter((key) => registry[key].category === category).map((key) => {
                  const entry = registry[key];
                  return (
                    <CommandItem key={key} value={`${entry.label} ${key} ${entry.aliases.join(" ")}`} onSelect={() => { onChange(key); setOpen(false); }}>
                      <Check className={cn("mr-2 size-4", key === value ? "opacity-100" : "opacity-0")} />
                      <Icon iconKey={key} className="mr-2 size-5" />
                      <span className="flex-1 truncate">{entry.label}</span>
                      <span className="ml-2 truncate text-xs text-muted-foreground">{key}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
