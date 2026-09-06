import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { EntityGroup } from "@/api/types";
import {
  DEFAULT_LAYERS,
  type LayerChoices,
  isVisible,
  layerOf,
  onlyGroup,
  toggleEntity,
  toggleGroup,
  UNGROUPED_LAYER,
} from "@/components/map/layerChoices";
import type { EntityFeatureProperties } from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { groupTree } from "@/hooks/useGroups";

interface Row {
  id: string;
  name: string;
  depth: number;
  color: string | null;
  members: EntityFeatureProperties[];
  total: number;
}

/** The map's layers (decision D98): groups and subgroups with their counts, show and hide per
 * group and per entity, "only", the ungrouped entities, features and recent events. */
export function LayerPanel({
  features,
  groups,
  choices,
  onChange,
  onClose,
  onPick,
}: {
  features: EntityFeatureProperties[];
  groups: EntityGroup[] | undefined;
  choices: LayerChoices;
  onChange: (next: LayerChoices) => void;
  onClose: () => void;
  onPick: (entityId: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const rows = useMemo<Row[]>(() => {
    const byLayer = new Map<string, EntityFeatureProperties[]>();
    for (const f of features) {
      const key = layerOf(f);
      byLayer.set(key, [...(byLayer.get(key) ?? []), f]);
    }
    const sorted = (list: EntityFeatureProperties[] | undefined) =>
      [...(list ?? [])].sort((a, b) => a.name.localeCompare(b.name));
    const out: Row[] = groupTree(groups).map(({ group, depth }) => {
      const members = sorted(byLayer.get(group.id));
      const below =
        depth === 0
          ? (groups ?? [])
              .filter((g) => g.parent_id === group.id)
              .reduce((n, g) => n + (byLayer.get(g.id)?.length ?? 0), 0)
          : 0;
      return {
        id: group.id,
        name: group.name,
        depth,
        color: group.color ?? null,
        members,
        total: members.length + below,
      };
    });
    const loose = sorted(byLayer.get(UNGROUPED_LAYER));
    if (loose.length > 0 || out.length > 0)
      out.push({
        id: UNGROUPED_LAYER,
        name: t("Ungrouped"),
        depth: 0,
        color: null,
        members: loose,
        total: loose.length,
      });
    return out;
  }, [features, groups, t]);
  const visibleCount = features.filter((f) =>
    isVisible(f, choices, groups),
  ).length;
  const isGroupShown = (id: string) => {
    if (choices.hidden_groups.includes(id)) return false;
    const parent = groups?.find((g) => g.id === id)?.parent_id;
    return !(parent && choices.hidden_groups.includes(parent));
  };
  const flip = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const customised =
    choices.hidden_groups.length > 0 ||
    choices.hidden_entities.length > 0 ||
    !choices.features ||
    !choices.events;
  return (
    <aside
      className="absolute left-3 top-14 z-10 max-h-[60%] w-72 overflow-y-auto rounded-lg border bg-card p-3 text-sm shadow-lg"
      aria-label={t("Map layers")}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">{t("Layers")}</span>
        <span className="flex items-center gap-1">
          {customised && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onChange(DEFAULT_LAYERS)}
            >
              {t("Show all")}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={t("Close")}
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </span>
      </div>
      <div className="mb-1 text-xs text-muted-foreground">
        {t("{{visible}} of {{total}} entities shown", {
          visible: visibleCount,
          total: features.length,
        })}
      </div>
      {rows.length === 0 && (
        <div className="py-1 text-xs text-muted-foreground">
          {t("No entities with a position yet.")}
        </div>
      )}
      <ul className="space-y-0.5">
        {rows.map((row) => {
          const shown = isGroupShown(row.id);
          const open = expanded.has(row.id);
          return (
            <li key={row.id}>
              <div
                className="group flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-muted"
                style={{ paddingLeft: 4 + row.depth * 16 }}
              >
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-5"
                  aria-label={open ? t("Collapse") : t("Expand")}
                  onClick={() => flip(row.id)}
                  disabled={row.members.length === 0}
                >
                  {open ? (
                    <ChevronDown className="size-3.5" />
                  ) : (
                    <ChevronRight className="size-3.5" />
                  )}
                </Button>
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={shown}
                  aria-label={row.name}
                  onChange={(e) =>
                    onChange(
                      toggleGroup(choices, row.id, e.target.checked, groups),
                    )
                  }
                />
                {row.color && (
                  <span
                    className="inline-block size-2.5 rounded-full"
                    style={{ background: row.color }}
                  />
                )}
                <span
                  className={`flex-1 truncate ${shown ? "" : "text-muted-foreground"}`}
                >
                  {row.name}
                </span>
                <span className="text-xs text-muted-foreground">
                  {row.total}
                </span>
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0 text-xs opacity-0 group-hover:opacity-100 focus:opacity-100"
                  onClick={() => onChange(onlyGroup(choices, row.id, groups))}
                >
                  {t("only")}
                </Button>
              </div>
              {open && (
                <ul>
                  {row.members.map((m) => {
                    const entityShown =
                      shown && !choices.hidden_entities.includes(m.entity_id);
                    return (
                      <li
                        key={m.entity_id}
                        className="flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-muted"
                        style={{ paddingLeft: 30 + row.depth * 16 }}
                      >
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          checked={entityShown}
                          disabled={!shown}
                          aria-label={m.name}
                          onChange={(e) =>
                            onChange(
                              toggleEntity(
                                choices,
                                m.entity_id,
                                e.target.checked,
                              ),
                            )
                          }
                        />
                        <button
                          type="button"
                          className={`flex-1 truncate text-left hover:underline ${entityShown ? "" : "text-muted-foreground"}`}
                          onClick={() => onPick(m.entity_id)}
                        >
                          {m.name}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      <div className="mt-2 space-y-1 border-t pt-2">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={choices.features}
            onChange={(e) =>
              onChange({ ...choices, features: e.target.checked })
            }
          />
          {t("Features")}
          <span className="text-xs text-muted-foreground">
            {t("sites, zones, geofences, routes")}
          </span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={choices.events}
            onChange={(e) => onChange({ ...choices, events: e.target.checked })}
          />
          {t("Events, 24 h")}
        </label>
      </div>
    </aside>
  );
}
