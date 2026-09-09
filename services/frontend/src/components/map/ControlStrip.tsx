import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * The map's control strip (phase 19, decision D137): one vertical column of square icon buttons
 * in the top right under MapLibre's own zoom and locate controls, rendered into a MapLibre
 * control host so it stacks with them at any height. One style for every control: the card
 * colour, a tooltip with the name, the active one filled, a count badge where a control has one.
 * Later parts add rows (heatmap, draw, measure, terrain) without touching the layout.
 */
export interface StripButton {
  kind?: "button";
  key: string;
  icon: LucideIcon;
  label: string;
  active?: boolean;
  disabled?: boolean;
  /** A small count on the button, for example the number of tracks on. */
  badge?: number;
  onClick: () => void;
}

export interface StripMenu {
  kind: "menu";
  key: string;
  icon: LucideIcon;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}

export type StripItem = StripButton | StripMenu;

const BUTTON = "size-9 rounded-md border bg-card shadow-sm";

function StripButtonView({ item }: { item: StripButton }) {
  const Icon = item.icon;
  return (
    <span className="relative">
      <Button
        type="button"
        variant={item.active ? "default" : "outline"}
        size="icon"
        className={item.active ? "size-9 rounded-md shadow-sm" : BUTTON}
        aria-label={item.label}
        aria-pressed={item.active}
        title={item.label}
        disabled={item.disabled}
        onClick={item.onClick}
      >
        <Icon className="size-4" />
      </Button>
      {item.badge != null && item.badge > 0 && (
        <span className="pointer-events-none absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-sand px-1 text-[10px] font-semibold leading-none text-foreground">
          {item.badge}
        </span>
      )}
    </span>
  );
}

function StripMenuView({ item }: { item: StripMenu }) {
  const Icon = item.icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={BUTTON}
          aria-label={item.label}
          title={item.label}
        >
          <Icon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="left" align="start">
        <DropdownMenuRadioGroup
          value={item.value}
          onValueChange={item.onChange}
        >
          {item.options.map((o) => (
            <DropdownMenuRadioItem key={o.value} value={o.value}>
              {o.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ControlStrip({
  items,
  children,
}: {
  items: StripItem[];
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col gap-1.5"
      role="toolbar"
      aria-label={t("Map tools")}
      aria-orientation="vertical"
    >
      {items.map((item) =>
        item.kind === "menu" ? (
          <StripMenuView key={item.key} item={item} />
        ) : (
          <StripButtonView key={item.key} item={item} />
        ),
      )}
      {children}
    </div>
  );
}
