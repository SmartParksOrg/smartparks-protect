import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityType, Page } from "@/api/types";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProject } from "@/hooks/useProjects";
import { hiddenTypeIds, splitSelection, subtypesOf, topLevel, visibleTypes } from "@/lib/entityTypes";
import { cn } from "@/lib/utils";

const NONE = "__none__";

/** The type and the sub-type of an entity as two controls (decision D169): a short select
 * of types, then a searchable list of that type's sub-types with their icons. The value is
 * the most specific row's id. With a project, the types hidden in its settings stay out. */
export function EntityTypeSelect({ id, projectId, value, onChange, disabled, noneLabel }: { id: string; projectId?: string; value: string; onChange: (id: string) => void; disabled?: boolean; noneLabel?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const types = useQuery({ queryKey: queryKeys.entityTypes, queryFn: () => api.get<Page<EntityType>>("/api/v1/entity-types", { query: { limit: 500 } }) });
  const { project } = useProject(projectId);
  const all = types.data?.items ?? [];
  const visible = visibleTypes(all, hiddenTypeIds(project?.settings));
  const { typeId, subtypeId } = splitSelection(all, value);
  const chosenType = all.find((x) => x.id === typeId);
  const subtypes = typeId ? subtypesOf(visible, typeId) : [];
  const chosenSubtype = subtypes.find((x) => x.id === subtypeId);
  // a type the project hid but this entity still has stays choosable, so an edit does not lose it
  const typeOptions = topLevel(chosenType && !visible.includes(chosenType) ? [chosenType, ...visible] : visible);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Select value={typeId || (noneLabel ? NONE : "")} onValueChange={(v) => onChange(v === NONE ? "" : v)} disabled={disabled}>
        <SelectTrigger id={id} aria-label={t("Type")}><SelectValue placeholder={t("Choose a type")} /></SelectTrigger>
        <SelectContent>
          {noneLabel && <SelectItem value={NONE}>{noneLabel}</SelectItem>}
          {typeOptions.map((x) => (
            <SelectItem key={x.id} value={x.id}><span className="inline-flex items-center gap-2"><Icon iconKey={x.icon_key} className="size-4" />{x.label}</span></SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button id={`${id}-subtype`} type="button" variant="outline" role="combobox" aria-expanded={open} aria-label={t("Sub-type")} disabled={disabled || !typeId || subtypes.length === 0} className="w-full justify-between font-normal">
            <span className={cn("inline-flex min-w-0 items-center gap-2", !chosenSubtype && "text-muted-foreground")}>
              {chosenSubtype && <Icon iconKey={chosenSubtype.icon_key} className="size-4" />}
              <span className="truncate">{chosenSubtype ? chosenSubtype.label : typeId && subtypes.length === 0 ? t("No sub-types") : t("Sub-type (optional)")}</span>
            </span>
            <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <Command>
            <CommandInput placeholder={t("Search sub-types…")} />
            <CommandList>
              <CommandEmpty>{t("Nothing matches.")}</CommandEmpty>
              <CommandGroup>
                <CommandItem value="__type_only__" onSelect={() => { onChange(typeId); setOpen(false); }}>
                  <Check className={cn("mr-2 size-4", !subtypeId ? "opacity-100" : "opacity-0")} />
                  <span className="text-muted-foreground">{t("Only {{type}}", { type: chosenType?.label ?? "" })}</span>
                </CommandItem>
                {subtypes.map((x) => (
                  <CommandItem key={x.id} value={x.label} onSelect={() => { onChange(x.id); setOpen(false); }}>
                    <Check className={cn("mr-2 size-4", x.id === subtypeId ? "opacity-100" : "opacity-0")} />
                    <Icon iconKey={x.icon_key} className="mr-2 size-5" />
                    <span className="truncate">{x.label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
