import { useTranslation } from "react-i18next";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityGroup } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { groupPath, useGroups } from "@/hooks/useGroups";

/** Move a selection of entities into a group, out of every group, or into a group created on
 * the spot inside the chosen one (decision D98). */
export function MoveToGroupDialog({
  projectId,
  entityIds,
  open,
  onOpenChange,
  onMoved,
}: {
  projectId: string;
  entityIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMoved?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("Move {{count}} entities", { count: entityIds.length })}
          </DialogTitle>
        </DialogHeader>
        {open && (
          <MoveForm
            projectId={projectId}
            entityIds={entityIds}
            onDone={() => {
              onOpenChange(false);
              onMoved?.();
            }}
            onCancel={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MoveForm({
  projectId,
  entityIds,
  onDone,
  onCancel,
}: {
  projectId: string;
  entityIds: string[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const groups = useGroups(projectId);
  const [target, setTarget] = useState("");
  const [newName, setNewName] = useState("");
  const move = useMutationToast({
    mutationFn: async () => {
      let groupId: string | null = target || null;
      if (newName.trim()) {
        const created = await api.post<EntityGroup>(
          `/api/v1/projects/${projectId}/groups`,
          { body: { name: newName.trim(), parent_id: groupId } },
        );
        groupId = created.id;
      }
      return api.post<{ moved: number }>(
        `/api/v1/projects/${projectId}/entities/bulk-move`,
        { body: { entity_ids: entityIds, group_id: groupId } },
      );
    },
    invalidate: [
      queryKeys.entities(projectId),
      queryKeys.groups(projectId),
      queryKeys.currentState(projectId),
      queryKeys.devices({ projectId }),
    ],
    success: (r) => t("{{count}} entities moved", { count: r.moved }),
    onSuccess: onDone,
  });
  const targetPath = target ? groupPath(groups.data, target) : t("no group");
  return (
    <>
      <div className="space-y-4">
        <Field label={t("Into")} htmlFor="move-target">
          <GroupSelect
            id="move-target"
            projectId={projectId}
            mode="choice"
            value={target}
            onChange={setTarget}
          />
        </Field>
        <Field
          label={t("Or into a new group")}
          htmlFor="move-new"
          hint={
            target
              ? t("Created inside {{path}}", { path: targetPath })
              : t("Created at the top level")
          }
        >
          <Input
            id="move-new"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("Name of the new group")}
          />
        </Field>
        {move.isError && <Callout kind="error">{move.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("Cancel")}
        </Button>
        <Button
          type="button"
          disabled={move.isPending}
          onClick={() => move.mutate()}
        >
          {move.isPending
            ? t("Moving…")
            : newName.trim()
              ? t("Create and move")
              : target
                ? t("Move")
                : t("Remove from groups")}
        </Button>
      </DialogFooter>
    </>
  );
}
