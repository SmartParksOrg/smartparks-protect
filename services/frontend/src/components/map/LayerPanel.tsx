import { useTranslation } from "react-i18next";
import {
  ArrowDownAZ,
  ArrowDownUp,
  ChevronDown,
  ChevronRight,
  LocateFixed,
  RadioTower,
  Route,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import type {
  CoverageResponse,
  EntityGroup,
  Feature,
  Gateway,
} from "@/api/types";
import { Icon } from "@/components/icons/Icon";
import {
  DEFAULT_LAYERS,
  hideAllDevices,
  hideAllEntities,
  hideDevices,
  isDeviceShown,
  isGroupShown,
  layerOf,
  onlyGroup,
  projectLayerOf,
  showDevices,
  showEntity,
  showEventType,
  showFeature,
  showFeatureType,
  showGateway,
  toggleDevice,
  toggleEntity,
  toggleGroup,
  toggleInList,
  type LayerChoices,
  UNGROUPED_LAYER,
  ungroupedLayerOf,
  withProjectShown,
} from "@/components/map/layerChoices";
import type {
  DeviceFeatureProperties,
  EntityFeatureProperties,
  EventFeatureProperties,
} from "@/components/map/layers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ancestorIds, groupTree } from "@/hooks/useGroups";
import { useParams } from "react-router";

import { useNow } from "@/hooks/useNow";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import { formatAgo, formatTime } from "@/lib/format";

type Sort = "name" | "recent";
type Tab = "entities" | "devices" | "features" | "events" | "coverage";

interface GroupRow {
  id: string;
  name: string;
  depth: number;
  color: string | null;
  /** A project row of the all scope: no "only", its groups below it. */
  project?: boolean;
  /** The rows above this one (groups, and the project in the all scope): folding any of them
   * hides this row. */
  parents: string[];
  members: EntityFeatureProperties[];
  total: number;
}

const matches = (name: string, term: string) =>
  !term || name.toLowerCase().includes(term);

function Row({
  depth,
  children,
  header,
}: {
  depth: number;
  children: ReactNode;
  header?: boolean;
}) {
  return (
    <div
      className={`group flex h-9 items-center gap-2 rounded-md pr-1 hover:bg-muted ${header ? "bg-muted/40" : ""}`}
      style={{ paddingLeft: 6 + depth * 18 }}
    >
      {children}
    </div>
  );
}

function Check({
  checked,
  indeterminate = false,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  /** Some of the rows below are on: shown as a dash, a click switches all of them on. */
  indeterminate?: boolean;
  disabled?: boolean;
  label: string;
  onChange: (on: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);
  return (
    <input
      ref={ref}
      type="checkbox"
      className="size-4 shrink-0 accent-primary"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

function Locate({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7 shrink-0 text-muted-foreground"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      <LocateFixed className="size-4" />
    </Button>
  );
}

/** The map's layers (decision D98): entities in their groups however deep, features and recent
 * events, each with search, show and hide per row, and a way to the object on the map. */
export function LayerPanel({
  entities,
  groups,
  features,
  events,
  gateways,
  coverage,
  choices,
  trackedIds,
  trackLabel,
  devices,
  trackedDeviceIds,
  projects,
  onChange,
  onClose,
  onPickEntity,
  onToggleTrack,
  onPickDevice,
  onToggleDeviceTrack,
  onPickFeature,
  onPickEvent,
  onPickGateway,
}: {
  entities: EntityFeatureProperties[];
  groups: EntityGroup[] | undefined;
  features: Feature[];
  events: EventFeatureProperties[];
  gateways: Gateway[];
  coverage: CoverageResponse | undefined;
  choices: LayerChoices;
  trackedIds: string[];
  /** The current track length, for the tooltip of the track button ("21 days"). */
  trackLabel: string;
  /** The device layer (decision D113): every device assigned to the project today. */
  devices: DeviceFeatureProperties[];
  trackedDeviceIds: string[];
  /** In the all-projects scope (decision D117): the projects, each the top level of its
   * groups, entities and devices. */
  projects?: { id: string; name: string }[];
  onChange: (next: LayerChoices) => void;
  onClose: () => void;
  onPickEntity: (entityId: string) => void;
  onToggleTrack: (entityId: string) => void;
  onPickDevice: (deviceId: string) => void;
  onToggleDeviceTrack: (deviceId: string) => void;
  onPickFeature: (featureId: string) => void;
  onPickEvent: (eventId: string) => void;
  onPickGateway: (gatewayId: string) => void;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const { projectId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("entities");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [grouped, setGrouped] = useState(true);
  // every row starts folded; a search opens what it reaches
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const term = q.trim().toLowerCase();
  const order = (a: EntityFeatureProperties, b: EntityFeatureProperties) =>
    sort === "name"
      ? a.name.localeCompare(b.name)
      : (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? "") ||
        a.name.localeCompare(b.name);

  const perProject = Boolean(projects);
  const rows = useMemo<GroupRow[]>(() => {
    const byLayer = new Map<string, EntityFeatureProperties[]>();
    for (const f of entities)
      byLayer.set(layerOf(f, perProject), [
        ...(byLayer.get(layerOf(f, perProject)) ?? []),
        f,
      ]);
    const rowsOf = (
      scopeGroups: EntityGroup[] | undefined,
      depthOffset: number,
      ungroupedId: string,
      parent: string | null,
    ): GroupRow[] => {
      const tree = groupTree(scopeGroups);
      const above = parent ? [parent] : [];
      const out: GroupRow[] = tree.map(({ group, depth }) => {
        const members = [...(byLayer.get(group.id) ?? [])].sort(order);
        const total = groupTree(scopeGroups, group.id, 1).reduce(
          (n, r) => n + (byLayer.get(r.group.id)?.length ?? 0),
          members.length,
        );
        return {
          id: group.id,
          name: group.name,
          depth: depth + depthOffset,
          color: group.color ?? null,
          parents: [...above, ...ancestorIds(scopeGroups, group.id)],
          members,
          total,
        };
      });
      const loose = [...(byLayer.get(ungroupedId) ?? [])].sort(order);
      if (loose.length > 0 || out.length > 0)
        out.push({
          id: ungroupedId,
          name: t("Ungrouped"),
          depth: depthOffset,
          color: null,
          parents: above,
          members: loose,
          total: loose.length,
        });
      return out;
    };
    if (!projects) return rowsOf(groups, 0, UNGROUPED_LAYER, null);
    // the all scope: every project as the top level (decision D117), busiest first by count
    const out: GroupRow[] = [];
    for (const project of [...projects].sort((a, b) => a.name.localeCompare(b.name))) {
      const own = (groups ?? []).filter((g) => g.project_id === project.id);
      const below = rowsOf(own, 1, ungroupedLayerOf(project.id), projectLayerOf(project.id));
      const total = entities.filter((e) => e.project_id === project.id).length;
      if (total === 0 && below.length === 0) continue;
      out.push({
        id: projectLayerOf(project.id),
        name: project.name,
        depth: 0,
        color: null,
        project: true,
        parents: [],
        members: [],
        total,
      });
      out.push(...below);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entities, groups, projects, perProject, sort, t]);

  const flip = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  /** Fold or unfold every row of a tab at once. */
  const foldAll = (keys: string[]) => {
    const anyOpen = keys.some((k) => expanded.has(k));
    return (
      <Button
        variant="ghost"
        size="sm"
        className="h-7 px-2 text-xs"
        disabled={keys.length === 0}
        onClick={() =>
          setExpanded((s) => {
            const next = new Set(s);
            for (const k of keys) if (anyOpen) next.delete(k);
            else next.add(k);
            return next;
          })
        }
      >
        {anyOpen ? t("Fold all") : t("Unfold all")}
      </Button>
    );
  };
  const shownCount = entities.filter(
    (f) =>
      isGroupShown(layerOf(f, perProject), choices, groups) &&
      !choices.hidden_entities.includes(f.entity_id),
  ).length;

  const siblingsOf = (m: EntityFeatureProperties) =>
    entities
      .filter(
        (e) =>
          layerOf(e, perProject) === layerOf(m, perProject) &&
          e.entity_id !== m.entity_id,
      )
      .map((e) => e.entity_id);
  const entityRow = (
    m: EntityFeatureProperties,
    depth: number,
    groupShown: boolean,
  ) => {
    const on = groupShown && !choices.hidden_entities.includes(m.entity_id);
    return (
      <Row key={m.entity_id} depth={depth}>
        <Check
          checked={on}
          label={m.name}
          onChange={(v) =>
            onChange(
              v
                ? showEntity(choices, m, groups, siblingsOf(m))
                : toggleEntity(choices, m.entity_id, false),
            )
          }
        />
        <ObjectPicture
          path={`/api/v1/projects/${projectId}/entities/${m.entity_id}/picture`}
          updatedAt={m.picture_updated_at}
          name={m.name}
          size="xs"
          className={on ? "" : "opacity-60"}
          fallback={
            <Icon
              iconKey={m.icon_key}
              className={`size-5 shrink-0 ${on ? "text-primary" : "text-muted-foreground"}`}
            />
          }
        />
        <button
          type="button"
          className={`min-w-0 flex-1 truncate text-left ${on ? "" : "text-muted-foreground"}`}
          onClick={() => onPickEntity(m.entity_id)}
        >
          {m.name}
        </button>
        <span
          className="shrink-0 text-[11px] text-muted-foreground"
          title={formatTime(m.last_seen_at)}
        >
          {formatAgo(m.last_seen_at, now)}
        </span>
        <Button
          variant={trackedIds.includes(m.entity_id) ? "default" : "ghost"}
          size="icon"
          className={`size-7 shrink-0 ${trackedIds.includes(m.entity_id) ? "" : "text-muted-foreground"}`}
          aria-pressed={trackedIds.includes(m.entity_id)}
          aria-label={
            trackedIds.includes(m.entity_id)
              ? t("Hide the track")
              : t("Show the track")
          }
          title={
            trackedIds.includes(m.entity_id)
              ? t("Hide the track")
              : t("Show the track, {{length}}", { length: trackLabel })
          }
          onClick={() => onToggleTrack(m.entity_id)}
        >
          <Route className="size-4" />
        </Button>
        <Locate
          label={t("Show on map")}
          onClick={() => onPickEntity(m.entity_id)}
        />
      </Row>
    );
  };

  const entitiesTab = (
    <>
      <div className="flex items-center gap-1.5 px-1 pb-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("Search…")}
          className="h-8"
          aria-label={t("Search layers")}
        />
        <Button
          variant={grouped ? "secondary" : "ghost"}
          size="sm"
          className="h-8 px-2 text-xs"
          aria-pressed={grouped}
          onClick={() => setGrouped((g) => !g)}
        >
          {t("Grouped")}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={
            sort === "name"
              ? t("Sorted by name, sort by last update")
              : t("Sorted by last update, sort by name")
          }
          title={sort === "name" ? t("By name") : t("By last update")}
          onClick={() => setSort((s) => (s === "name" ? "recent" : "name"))}
        >
          {sort === "name" ? (
            <ArrowDownAZ className="size-4" />
          ) : (
            <ArrowDownUp className="size-4" />
          )}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {entities.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {t("No entities with a position yet.")}
          </div>
        )}
        {grouped
          ? rows.map((row) => {
              const groupMatch = matches(row.name, term);
              const members = groupMatch
                ? row.members
                : row.members.filter((m) => matches(m.name, term));
              const belowMatch =
                term &&
                groupTree(groups, row.id, 1).some(
                  (r) =>
                    matches(r.group.name, term) ||
                    rows
                      .find((x) => x.id === r.group.id)
                      ?.members.some((m) => matches(m.name, term)),
                );
              if (term && !groupMatch && members.length === 0 && !belowMatch)
                return null;
              const shown = isGroupShown(row.id, choices, groups);
              const open = expanded.has(row.id) || Boolean(term);
              // folded above: the whole subtree goes, unless a search reaches into it
              if (!term && row.parents.some((p) => !expanded.has(p))) return null;
              return (
                <div key={row.id}>
                  <Row depth={row.depth} header>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6 shrink-0"
                      aria-label={open ? t("Collapse") : t("Expand")}
                      onClick={() => flip(row.id)}
                    >
                      {open ? (
                        <ChevronDown className="size-4" />
                      ) : (
                        <ChevronRight className="size-4" />
                      )}
                    </Button>
                    <Check
                      checked={shown}
                      label={row.name}
                      onChange={(v) =>
                        onChange(
                          v
                            ? withProjectShown(
                                toggleGroup(choices, row.id, v, groups),
                                row.id,
                                groups,
                              )
                            : toggleGroup(choices, row.id, v, groups),
                        )
                      }
                    />
                    {row.color && (
                      <span
                        className="inline-block size-2.5 shrink-0 rounded-full"
                        style={{ background: row.color }}
                      />
                    )}
                    <span
                      className={`min-w-0 flex-1 truncate font-semibold ${shown ? "" : "text-muted-foreground"}`}
                    >
                      {row.name}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {row.total}
                    </span>
                    {!row.project && (
                      <Button
                        variant="link"
                        size="sm"
                        className="h-auto shrink-0 p-0 text-xs opacity-0 group-hover:opacity-100 focus:opacity-100"
                        onClick={() =>
                          onChange(onlyGroup(choices, row.id, groups))
                        }
                      >
                        {t("only")}
                      </Button>
                    )}
                  </Row>
                  {open &&
                    members.map((m) => entityRow(m, row.depth + 1, shown))}
                </div>
              );
            })
          : [...entities]
              .filter((m) => matches(m.name, term))
              .sort(order)
              .map((m) =>
                entityRow(m, 0, isGroupShown(layerOf(m, perProject), choices, groups)),
              )}
      </div>
      <div className="flex items-center justify-between border-t px-1 pt-2 text-xs text-muted-foreground">
        <span>
          {t("{{shown}} of {{total}} shown", {
            shown: shownCount,
            total: entities.length,
          })}
        </span>
        <span className="flex gap-1">
          {foldAll(rows.map((r) => r.id))}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() =>
              onChange({ ...choices, hidden_groups: [], hidden_entities: [] })
            }
          >
            {t("Show all")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() =>
              onChange(
                hideAllEntities(choices, groups, projects?.map((p) => p.id) ?? []),
              )
            }
          >
            {t("Hide all")}
          </Button>
        </span>
      </div>
    </>
  );

  const featureTypes = [...new Set(features.map((f) => f.feature_type))].sort();
  const featuresTab = (
    <>
      <div className="flex items-center gap-1.5 px-1 pb-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("Search…")}
          className="h-8"
          aria-label={t("Search features")}
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        <Row depth={0} header>
          <Check
            checked={choices.features}
            label={t("Features")}
            onChange={(v) => onChange({ ...choices, features: v })}
          />
          <span className="min-w-0 flex-1 truncate font-semibold">
            {t("Features")}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {features.length}
          </span>
        </Row>
        {features.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {t("No features drawn yet.")}
          </div>
        )}
        {featureTypes.map((type) => {
          const items = features
            .filter((f) => f.feature_type === type && matches(f.name, term))
            .sort((a, b) => a.name.localeCompare(b.name));
          if (term && items.length === 0) return null;
          const typeOn =
            choices.features && !choices.hidden_feature_types.includes(type);
          const open = expanded.has(`ft:${type}`) || Boolean(term);
          return (
            <div key={type}>
              <Row depth={1} header>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6 shrink-0"
                  aria-label={open ? t("Collapse") : t("Expand")}
                  onClick={() => flip(`ft:${type}`)}
                >
                  {open ? (
                    <ChevronDown className="size-4" />
                  ) : (
                    <ChevronRight className="size-4" />
                  )}
                </Button>
                <Check
                  checked={typeOn}
                  label={t(type)}
                  onChange={(v) =>
                    onChange(
                      v
                        ? showFeatureType(choices, type, featureTypes)
                        : {
                            ...choices,
                            hidden_feature_types: toggleInList(
                              choices.hidden_feature_types,
                              type,
                              false,
                            ),
                          },
                    )
                  }
                />
                <span
                  className={`min-w-0 flex-1 truncate font-medium capitalize ${typeOn ? "" : "text-muted-foreground"}`}
                >
                  {t(type)}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {features.filter((f) => f.feature_type === type).length}
                </span>
              </Row>
              {open &&
                items.map((f) => {
                  const on = typeOn && !choices.hidden_features.includes(f.id);
                  return (
                    <Row key={f.id} depth={2}>
                      <Check
                        checked={on}
                        label={f.name}
                        onChange={(v) =>
                          onChange(
                            v
                              ? showFeature(
                                  choices,
                                  f,
                                  features
                                    .filter(
                                      (x) => x.feature_type === f.feature_type,
                                    )
                                    .map((x) => x.id),
                                  featureTypes,
                                )
                              : {
                                  ...choices,
                                  hidden_features: toggleInList(
                                    choices.hidden_features,
                                    f.id,
                                    false,
                                  ),
                                },
                          )
                        }
                      />
                      <button
                        type="button"
                        className={`min-w-0 flex-1 truncate text-left ${on ? "" : "text-muted-foreground"}`}
                        onClick={() => onPickFeature(f.id)}
                      >
                        {f.name}
                      </button>
                      <Locate
                        label={t("Show on map")}
                        onClick={() => onPickFeature(f.id)}
                      />
                    </Row>
                  );
                })}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-end border-t px-1 pt-2 text-xs text-muted-foreground">
        {foldAll(featureTypes.map((type) => `ft:${type}`))}
      </div>
    </>
  );

  const eventTypes = [...new Set(events.map((e) => e.event_type))].sort();
  const eventsTab = (
    <>
      <div className="flex items-center gap-1.5 px-1 pb-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("Search…")}
          className="h-8"
          aria-label={t("Search events")}
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        <Row depth={0} header>
          <Check
            checked={choices.events}
            label={t("Events, 24 h")}
            onChange={(v) => onChange({ ...choices, events: v })}
          />
          <span className="min-w-0 flex-1 truncate font-semibold">
            {t("Events, 24 h")}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {events.length}
          </span>
        </Row>
        {events.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {t("No events with a position in the last 24 hours.")}
          </div>
        )}
        {eventTypes.map((type) => {
          const items = events
            .filter((e) => e.event_type === type && matches(e.title, term))
            .sort((a, b) => b.time.localeCompare(a.time));
          if (term && items.length === 0) return null;
          const typeOn =
            choices.events && !choices.hidden_event_types.includes(type);
          const open = expanded.has(`ev:${type}`) || Boolean(term);
          return (
            <div key={type}>
              <Row depth={1} header>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6 shrink-0"
                  aria-label={open ? t("Collapse") : t("Expand")}
                  onClick={() => flip(`ev:${type}`)}
                >
                  {open ? (
                    <ChevronDown className="size-4" />
                  ) : (
                    <ChevronRight className="size-4" />
                  )}
                </Button>
                <Check
                  checked={typeOn}
                  label={type}
                  onChange={(v) =>
                    onChange(
                      v
                        ? showEventType(choices, type, eventTypes)
                        : {
                            ...choices,
                            hidden_event_types: toggleInList(
                              choices.hidden_event_types,
                              type,
                              false,
                            ),
                          },
                    )
                  }
                />
                <span
                  className={`min-w-0 flex-1 truncate font-medium ${typeOn ? "" : "text-muted-foreground"}`}
                >
                  {type}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {events.filter((e) => e.event_type === type).length}
                </span>
              </Row>
              {open &&
                items.map((e) => (
                  <Row key={e.event_id} depth={2}>
                    <span
                      className={`inline-block size-2.5 shrink-0 rounded-full ${e.alert_status === "open" ? "bg-destructive" : e.severity === "warning" ? "bg-brand-sand" : "bg-muted-foreground/50"}`}
                    />
                    <Icon
                      iconKey={e.icon_key}
                      className={`size-4 shrink-0 ${typeOn ? "text-primary" : "text-muted-foreground"}`}
                    />
                    <button
                      type="button"
                      className={`min-w-0 flex-1 truncate text-left ${typeOn ? "" : "text-muted-foreground"}`}
                      onClick={() => onPickEvent(e.event_id)}
                    >
                      {e.title}
                    </button>
                    <span
                      className="shrink-0 text-[11px] text-muted-foreground"
                      title={formatTime(e.time)}
                    >
                      {formatAgo(e.time, now)}
                    </span>
                    <Locate
                      label={t("Show on map")}
                      onClick={() => onPickEvent(e.event_id)}
                    />
                  </Row>
                ))}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-end border-t px-1 pt-2 text-xs text-muted-foreground">
        {foldAll(eventTypes.map((type) => `ev:${type}`))}
      </div>
    </>
  );

  const placed = gateways
    .filter((g) => g.geometry)
    .sort((a, b) => a.display_name.localeCompare(b.display_name));
  const PERIODS = [24, 168, 720, 2160];
  const periodLabel = (hours: number) =>
    hours < 48
      ? t("{{count}} hours", { count: hours })
      : t("{{count}} days", { count: Math.round(hours / 24) });
  const heardBy = new Map(
    (coverage?.gateways ?? []).map((g) => [g.gateway_id ?? g.external_id, g]),
  );
  const deviceOrder = (a: DeviceFeatureProperties, b: DeviceFeatureProperties) =>
    sort === "name"
      ? a.name.localeCompare(b.name)
      : (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? "") ||
        a.name.localeCompare(b.name);
  const listedDevices = devices
    .filter((d) => matches(d.name, term) || matches(d.serial_number ?? "", term))
    .sort(deviceOrder);
  const deviceSections = (
    projects
      ? [
          ...[...projects]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((p) => ({
              key: p.id,
              name: p.name,
              devices: listedDevices.filter((d) => d.project_id === p.id),
            })),
          // a server admin sees inventory too (decision D120): devices in no project
          {
            key: "none",
            name: t("Not in a project"),
            devices: listedDevices.filter((d) => !d.project_id),
          },
        ].filter((sec) => sec.devices.length > 0)
      : [{ key: "all", name: null, devices: listedDevices }]
  ).map((sec) => ({
    key: sec.key,
    name: sec.name,
    unassigned: sec.devices.filter((d) => !d.entity_id),
    tracking: sec.devices.filter((d) => d.entity_id),
  }));
  const shownDevices = devices.filter((d) => isDeviceShown(d.device_id, choices)).length;
  const deviceRow = (d: DeviceFeatureProperties) => {
    const on = isDeviceShown(d.device_id, choices);
    return (
      <Row key={d.device_id} depth={1}>
        <Check
          checked={on}
          label={d.name}
          onChange={(v) => onChange(toggleDevice(choices, d.device_id, v))}
        />
        <ObjectPicture
          path={`/api/v1/devices/${d.device_id}/picture`}
          updatedAt={d.picture_updated_at}
          name={d.name}
          size="xs"
          className={on ? "" : "opacity-60"}
          fallback={
            <Icon
              iconKey={d.icon_key}
              className={`size-5 shrink-0 ${on ? "text-primary" : "text-muted-foreground"}`}
            />
          }
        />
        <button
          type="button"
          className={`min-w-0 flex-1 truncate text-left ${on ? "" : "text-muted-foreground"}`}
          title={d.entity_name ? t("Tracks {{name}}", { name: d.entity_name }) : d.name}
          onClick={() => onPickDevice(d.device_id)}
        >
          {d.name}
          {d.entity_name && (
            <span className="ml-1 text-[11px] text-muted-foreground">
              {d.entity_name}
            </span>
          )}
        </button>
        <span
          className="shrink-0 text-[11px] text-muted-foreground"
          title={formatTime(d.last_seen_at)}
        >
          {formatAgo(d.last_seen_at, now)}
        </span>
        <Button
          variant={trackedDeviceIds.includes(d.device_id) ? "default" : "ghost"}
          size="icon"
          className={`size-7 shrink-0 ${trackedDeviceIds.includes(d.device_id) ? "" : "text-muted-foreground"}`}
          aria-pressed={trackedDeviceIds.includes(d.device_id)}
          aria-label={
            trackedDeviceIds.includes(d.device_id)
              ? t("Hide the track")
              : t("Show the track")
          }
          title={
            trackedDeviceIds.includes(d.device_id)
              ? t("Hide the track")
              : t("Show the track, {{length}}", { length: trackLabel })
          }
          onClick={() => onToggleDeviceTrack(d.device_id)}
        >
          <Route className="size-4" />
        </Button>
        {d.position_time ? (
          <Locate label={t("Show on map")} onClick={() => onPickDevice(d.device_id)} />
        ) : (
          <span className="size-7 shrink-0" title={t("No position yet")} />
        )}
      </Row>
    );
  };
  const devicesTab = (
    <>
      <div className="flex items-center gap-1.5 px-1 pb-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("Search…")}
          className="h-8"
          aria-label={t("Search devices")}
        />
        <Button
          variant="outline"
          size="icon"
          className="size-8 shrink-0"
          aria-label={sort === "name" ? t("Sort by last update") : t("Sort by name")}
          title={sort === "name" ? t("Sort by last update") : t("Sort by name")}
          onClick={() => setSort(sort === "name" ? "recent" : "name")}
        >
          <ArrowDownUp className="size-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {devices.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">
            {t("No device is assigned to this project.")}
          </div>
        )}
        {deviceSections.map((section) => {
          const all = [...section.unassigned, ...section.tracking];
          const ids = all.map((d) => d.device_id);
          const onCount = ids.filter((id) => isDeviceShown(id, choices)).length;
          const foldKey = `dev:${section.key}`;
          const open = !section.name || expanded.has(foldKey) || Boolean(term);
          const openU = expanded.has(`${foldKey}:u`) || Boolean(term);
          const openT = expanded.has(`${foldKey}:t`) || Boolean(term);
          const foldButton = (key: string, isOpen: boolean) => (
            <Button
              variant="ghost"
              size="icon"
              className="size-6 shrink-0"
              aria-label={isOpen ? t("Collapse") : t("Expand")}
              onClick={() => flip(key)}
            >
              {isOpen ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronRight className="size-4" />
              )}
            </Button>
          );
          return (
          <div key={section.key}>
            {section.name && (
              <Row depth={0} header>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6 shrink-0"
                  aria-label={open ? t("Collapse") : t("Expand")}
                  onClick={() => flip(foldKey)}
                >
                  {open ? (
                    <ChevronDown className="size-4" />
                  ) : (
                    <ChevronRight className="size-4" />
                  )}
                </Button>
                <Check
                  checked={ids.length > 0 && onCount === ids.length}
                  indeterminate={onCount > 0 && onCount < ids.length}
                  label={section.name}
                  onChange={(v) =>
                    onChange(v ? showDevices(choices, ids) : hideDevices(choices, ids))
                  }
                />
                <span
                  className={`min-w-0 flex-1 truncate font-semibold ${onCount > 0 ? "" : "text-muted-foreground"}`}
                >
                  {section.name}
                </span>
                <span className="text-xs text-muted-foreground">
                  {onCount > 0 ? `${onCount} / ` : ""}
                  {all.length}
                </span>
              </Row>
            )}
            {open && section.unassigned.length > 0 && (
              <Row depth={section.name ? 1 : 0} header>
                {foldButton(`${foldKey}:u`, openU)}
                <span className="min-w-0 flex-1 truncate font-semibold">
                  {t("Without an entity")}
                </span>
                <span className="text-xs text-muted-foreground">
                  {section.unassigned.length}
                </span>
              </Row>
            )}
            {open && openU && section.unassigned.map(deviceRow)}
            {open && section.tracking.length > 0 && (
              <Row depth={section.name ? 1 : 0} header>
                {foldButton(`${foldKey}:t`, openT)}
                <span className="min-w-0 flex-1 truncate font-semibold">
                  {t("Tracking an entity")}
                </span>
                <span className="text-xs text-muted-foreground">
                  {section.tracking.length}
                </span>
              </Row>
            )}
            {open && openT && section.tracking.map(deviceRow)}
          </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between border-t px-1 pt-2 text-xs text-muted-foreground">
        <span>
          {t("{{shown}} of {{total}} shown", { shown: shownDevices, total: devices.length })}
        </span>
        <span className="flex gap-1">
          {foldAll(
            deviceSections.flatMap((sec) => [
              `dev:${sec.key}`,
              `dev:${sec.key}:u`,
              `dev:${sec.key}:t`,
            ]),
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() =>
              onChange(showDevices(choices, listedDevices.map((d) => d.device_id)))
            }
          >
            {t("Show all")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onChange(hideAllDevices(choices))}
          >
            {t("Hide all")}
          </Button>
        </span>
      </div>
    </>
  );

  const coverageTab = (
    <>
      <div className="flex items-center gap-1.5 px-1 pb-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("Search…")}
          className="h-8"
          aria-label={t("Search gateways")}
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        <Row depth={0} header>
          <Check
            checked={choices.coverage}
            label={t("Heard positions")}
            onChange={(v) => onChange({ ...choices, coverage: v })}
          />
          <span className="min-w-0 flex-1 truncate font-semibold">
            {t("Heard positions")}
          </span>
          <Select
            value={String(choices.coverage_hours)}
            onValueChange={(v) =>
              onChange({ ...choices, coverage_hours: Number(v) })
            }
          >
            <SelectTrigger
              className="h-7 w-24 text-xs"
              aria-label={t("Period")}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIODS.map((hours) => (
                <SelectItem key={hours} value={String(hours)}>
                  {periodLabel(hours)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Row>
        {choices.coverage && (
          <div className="space-y-1 px-2 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <span>{t("-120 dBm")}</span>
              <span
                className="h-2 flex-1 rounded"
                style={{
                  background:
                    "linear-gradient(90deg, #b91c1c, #f59e0b, #a3c14a, #15803d)",
                }}
              />
              <span>{t("-80 dBm")}</span>
            </div>
            <div>
              {coverage
                ? coverage.mode === "hexagons"
                  ? t(
                      "{{count}} heard positions in view, as hexagons of about {{size}} m",
                      { count: coverage.total, size: coverage.hexagon_m ?? 0 },
                    )
                  : t("{{count}} heard positions in view", {
                      count: coverage.total,
                    })
                : t("Loading…")}
            </div>
            <div>
              {t(
                "Only where collars were: a blank area may still have coverage.",
              )}
            </div>
          </div>
        )}
        <Row depth={0} header>
          <Check
            checked={choices.gateways}
            label={t("Gateways")}
            onChange={(v) => onChange({ ...choices, gateways: v })}
          />
          <span className="min-w-0 flex-1 truncate font-semibold">
            {t("Gateways")}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {placed.length}
          </span>
        </Row>
        {placed.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {t("No gateway with a position yet.")}
          </div>
        )}
        {placed
          .filter((g) => matches(g.display_name, term))
          .map((g) => {
            const on =
              choices.gateways && !choices.hidden_gateways.includes(g.id);
            const heard = heardBy.get(g.id);
            return (
              <Row key={g.id} depth={1}>
                <Check
                  checked={on}
                  label={g.display_name}
                  onChange={(v) =>
                    onChange(
                      v
                        ? showGateway(
                            choices,
                            g.id,
                            placed.map((x) => x.id),
                          )
                        : {
                            ...choices,
                            hidden_gateways: toggleInList(
                              choices.hidden_gateways,
                              g.id,
                              false,
                            ),
                          },
                    )
                  }
                />
                <RadioTower
                  className={`size-4 shrink-0 ${on ? "text-primary" : "text-muted-foreground"}`}
                />
                <button
                  type="button"
                  className={`min-w-0 flex-1 truncate text-left ${on ? "" : "text-muted-foreground"}`}
                  onClick={() => onPickGateway(g.id)}
                >
                  {g.display_name}
                </button>
                {choices.coverage && heard ? (
                  <span
                    className="shrink-0 text-[11px] text-muted-foreground"
                    title={t("Heard positions and share")}
                  >
                    {heard.heard} · {Math.round(heard.share * 100)}%
                  </span>
                ) : (
                  <span
                    className="shrink-0 text-[11px] text-muted-foreground"
                    title={formatTime(g.last_seen_at)}
                  >
                    {formatAgo(g.last_seen_at, now)}
                  </span>
                )}
                <Locate
                  label={t("Show on map")}
                  onClick={() => onPickGateway(g.id)}
                />
              </Row>
            );
          })}
        {gateways.length > placed.length && (
          <div className="px-2 py-2 text-xs text-muted-foreground">
            {t("{{count}} gateways without a position are not on the map.", {
              count: gateways.length - placed.length,
            })}
          </div>
        )}
      </div>
    </>
  );

  const customised = JSON.stringify(choices) !== JSON.stringify(DEFAULT_LAYERS);
  return (
    <aside
      className="absolute inset-y-0 left-0 z-20 flex w-[22rem] max-w-full flex-col border-r bg-card text-sm shadow-lg"
      aria-label={t("Map layers")}
    >
      <div className="flex items-center justify-between px-3 pt-3">
        <span className="text-base font-semibold">{t("Map layers")}</span>
        <span className="flex items-center gap-1">
          {customised && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onChange(DEFAULT_LAYERS)}
            >
              {t("Reset")}
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
      <Tabs
        value={tab}
        onValueChange={(v) => {
          setTab(v as Tab);
          setQ("");
        }}
        className="px-3 pt-1"
      >
        <TabsList className="w-full">
          <TabsTrigger value="entities" className="flex-1">
            {t("Entities")}
          </TabsTrigger>
          <TabsTrigger value="devices" className="flex-1">
            {t("Devices")}
          </TabsTrigger>
          <TabsTrigger value="features" className="flex-1">
            {t("Features")}
          </TabsTrigger>
          <TabsTrigger value="events" className="flex-1">
            {t("Events")}
          </TabsTrigger>
          <TabsTrigger value="coverage" className="flex-1">
            {t("Coverage")}
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <div className="flex min-h-0 flex-1 flex-col px-2 pb-2 pt-2">
        {tab === "entities" && entitiesTab}
        {tab === "devices" && devicesTab}
        {tab === "features" && featuresTab}
        {tab === "events" && eventsTab}
        {tab === "coverage" && coverageTab}
      </div>
    </aside>
  );
}
