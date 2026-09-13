import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type {
  Device,
  Entity,
  MemberScope,
  Page as PageType,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { orderTree } from "@/components/members/tree";
import { useGroups } from "@/hooks/useGroups";

/** Pick what a member sees: groups (with everything below), entities and devices. */
export function ScopeDialog({
  projectId,
  title,
  value,
  pending,
  onClose,
  onSave,
}: {
  projectId: string;
  title: string;
  value: MemberScope | null;
  pending: boolean;
  onClose: () => void;
  onSave: (scope: MemberScope | null) => void;
}) {
  const { t } = useTranslation();
  const groups = useGroups(projectId);
  const entities = useQuery({
    queryKey: ["projects", projectId, "entities", "scope-picker"],
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const devices = useQuery({
    queryKey: ["devices", projectId, "scope-picker"],
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
  });
  const [chosenGroups, setChosenGroups] = useState<Set<string>>(
    new Set(value?.groups ?? []),
  );
  const [chosenEntities, setChosenEntities] = useState<Set<string>>(
    new Set(value?.entities ?? []),
  );
  const [chosenDevices, setChosenDevices] = useState<Set<string>>(
    new Set(value?.devices ?? []),
  );
  const [term, setTerm] = useState("");
  const flip = (set: Set<string>, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };
  const tree = useMemo(() => orderTree(groups.data ?? []), [groups.data]);
  const lower = term.toLowerCase();
  const entityRows = (entities.data?.items ?? []).filter(
    (e) => !lower || e.name.toLowerCase().includes(lower),
  );
  const deviceRows = (devices.data?.items ?? []).filter(
    (d) => !lower || d.name.toLowerCase().includes(lower),
  );
  const nothing =
    chosenGroups.size + chosenEntities.size + chosenDevices.size === 0;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {t(
              "Nothing ticked means the whole project. A ticked group brings everything below it; a ticked entity brings the device tracking it.",
            )}
          </DialogDescription>
        </DialogHeader>
        <Input
          placeholder={t("Search entities and devices…")}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Groups")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {tree.map(({ group, depth }) => (
                <label
                  key={group.id}
                  className="flex items-center gap-2"
                  style={{ paddingLeft: depth * 12 }}
                >
                  <input
                    type="checkbox"
                    className="accent-primary"
                    checked={chosenGroups.has(group.id)}
                    onChange={() => setChosenGroups((s) => flip(s, group.id))}
                  />
                  <span className="truncate">{group.name}</span>
                </label>
              ))}
              {tree.length === 0 && (
                <p className="text-muted-foreground">{t("No groups.")}</p>
              )}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Entities")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {entityRows.map((e) => (
                <label key={e.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="accent-primary"
                    checked={chosenEntities.has(e.id)}
                    onChange={() => setChosenEntities((s) => flip(s, e.id))}
                  />
                  <span className="truncate">{e.name}</span>
                </label>
              ))}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-medium">{t("Devices")}</h3>
            <div className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {deviceRows.map((d) => (
                <label key={d.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="accent-primary"
                    checked={chosenDevices.has(d.id)}
                    onChange={() => setChosenDevices((s) => flip(s, d.id))}
                  />
                  <span className="truncate">{d.name}</span>
                </label>
              ))}
            </div>
          </section>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setChosenGroups(new Set());
              setChosenEntities(new Set());
              setChosenDevices(new Set());
            }}
          >
            {t("Everything")}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={pending}
            onClick={() =>
              onSave(
                nothing
                  ? null
                  : {
                      groups: [...chosenGroups],
                      entities: [...chosenEntities],
                      devices: [...chosenDevices],
                    },
              )
            }
          >
            {t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
