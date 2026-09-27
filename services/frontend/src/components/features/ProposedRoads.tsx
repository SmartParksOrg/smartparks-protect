import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MAX_READ_KM2,
  readVerdict,
  type ReadBox,
} from "@/components/map/proposeBox";
import { Button } from "@/components/ui/button";
import type {
  ProposedRoad,
  ProposedRoads as Roads,
} from "@/hooks/useProposeRoads";

/**
 * The roads a box read from OpenStreetMap (phase 38, decision D300), under the drawing map of
 * a new route: every way with a checkbox, its name and its kind, Use to put one in the editor,
 * or the ticked ones as one route. The ways people walk on are already left out by the read.
 */
export function ProposedRoads({
  roads,
  busy,
  error,
  reading,
  onPick,
  onCombine,
  onCancel,
}: {
  roads: Roads | null;
  busy: boolean;
  error: string | null;
  /** The ground the last gesture chose, for its size and the refusal (decision D277). */
  reading?: ReadBox | null;
  onPick: (road: ProposedRoad) => void;
  /** The ticked roads as one route: a MultiLineString the editor keeps as it came. */
  onCombine: (roads: ProposedRoad[]) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const verdict = reading ? readVerdict(reading) : null;
  const items = roads?.roads ?? [];
  const chosen = items.filter((r) => ticked.has(r.osm_id));
  const toggle = (id: number) =>
    setTicked((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div className="space-y-2">
      {verdict && (
        <p
          className={
            verdict.tooLarge
              ? "text-xs text-destructive"
              : "text-xs text-muted-foreground"
          }
        >
          {verdict.tooLarge
            ? t(
                "That box is {{km2}} km²; a read takes at most {{max}} km². Draw a smaller one.",
                { km2: verdict.km2.toFixed(0), max: MAX_READ_KM2 },
              )
            : verdict.warn
              ? t("{{km2}} km²; a box this size may take a while.", {
                  km2: verdict.km2.toFixed(1),
                })
              : t("{{km2}} km²", { km2: verdict.km2.toFixed(1) })}
        </p>
      )}
      {busy && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          {t("Reading OpenStreetMap…")}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7"
            onClick={onCancel}
          >
            {t("Cancel")}
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {!busy && roads && items.length === 0 && (
        <p className="text-xs text-muted-foreground">
          {t("No roads or tracks in that box.")}
        </p>
      )}
      {items.length > 0 && (
        <>
          <div className="max-h-48 overflow-y-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card text-left text-xs text-muted-foreground">
                <tr>
                  <th className="w-8 px-2 py-1">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      aria-label={t("Tick every road")}
                      checked={chosen.length === items.length}
                      onChange={(e) =>
                        setTicked(
                          e.target.checked
                            ? new Set(items.map((r) => r.osm_id))
                            : new Set(),
                        )
                      }
                    />
                  </th>
                  <th className="px-2 py-1">{t("Name")}</th>
                  <th className="px-2 py-1">{t("Kind")}</th>
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {items.map((road) => (
                  <tr key={road.osm_id} className="border-t">
                    <td className="px-2 py-1">
                      <input
                        type="checkbox"
                        className="size-4 accent-primary"
                        aria-label={t("Tick {{name}}", { name: road.name })}
                        checked={ticked.has(road.osm_id)}
                        onChange={() => toggle(road.osm_id)}
                      />
                    </td>
                    <td className="px-2 py-1">{road.name}</td>
                    <td className="px-2 py-1 text-xs text-muted-foreground">
                      {road.highway}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7"
                        onClick={() => onPick(road)}
                      >
                        {t("Use")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7"
              disabled={chosen.length < 1}
              onClick={() => onCombine(chosen)}
            >
              {t("Use {{count}} as one route", { count: chosen.length })}
            </Button>
            <span className="text-xs text-muted-foreground">
              {roads?.attribution}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
