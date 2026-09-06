import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { EntityGroup } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { groupTree, useGroups } from "@/hooks/useGroups";
import { useMutationToast } from "@/hooks/useMutationToast";

const schema = z.object({
  name: z.string().min(1, "Give the group a name").max(200),
  parent_id: z.string(),
  sort_order: z.string().regex(/^-?\d{0,4}$/, "A whole number"),
  color: z.string(),
  description: z.string(),
});
type Values = z.infer<typeof schema>;

function GroupDialog({
  projectId,
  group,
  parentId,
  open,
  onOpenChange,
}: {
  projectId: string;
  group: EntityGroup | null;
  parentId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const groups = useGroups(projectId);
  const parents = (groups.data ?? []).filter(
    (g) => !g.parent_id && g.id !== group?.id,
  );
  const hasChildren = Boolean(
    group && groups.data?.some((g) => g.parent_id === group.id),
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      parent_id: "",
      sort_order: "0",
      color: "",
      description: "",
    },
  });
  useEffect(() => {
    if (!open) return;
    form.reset({
      name: group?.name ?? "",
      parent_id: group?.parent_id ?? parentId ?? "",
      sort_order: String(group?.sort_order ?? 0),
      color: group?.color ?? "",
      description: group?.description ?? "",
    });
  }, [open, group, parentId, form]);
  const save = useMutationToast({
    mutationFn: (values: Values) => {
      const body = {
        name: values.name,
        parent_id: values.parent_id || null,
        sort_order: Number(values.sort_order) || 0,
        color: values.color || null,
        description: values.description || null,
      };
      return group
        ? api.patch<EntityGroup>(
            `/api/v1/projects/${projectId}/groups/${group.id}`,
            { body },
          )
        : api.post<EntityGroup>(`/api/v1/projects/${projectId}/groups`, {
            body,
          });
    },
    invalidate: [queryKeys.groups(projectId), queryKeys.entities(projectId)],
    success: group ? t("Group updated") : t("Group created"),
    onSuccess: () => onOpenChange(false),
    onError: (error) => form.setError("root", { message: error.message }),
  });
  const color = form.watch("color");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group ? t("Edit group") : t("New group")}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((v) => save.mutate(v))}
          noValidate
        >
          <Field
            label={t("Name")}
            htmlFor="group-name"
            error={form.formState.errors.name?.message}
          >
            <Input id="group-name" {...form.register("name")} />
          </Field>
          <Field
            label={t("Inside")}
            htmlFor="group-parent"
            hint={
              hasChildren
                ? t("This group has subgroups, so it stays at the top level")
                : t(
                    "Groups are two levels deep: a subgroup sits inside a top-level group",
                  )
            }
          >
            <Select
              value={form.watch("parent_id") || "none"}
              onValueChange={(v) =>
                form.setValue("parent_id", v === "none" ? "" : v)
              }
              disabled={hasChildren}
            >
              <SelectTrigger id="group-parent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("Top level")}</SelectItem>
                {parents.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field
              label={t("Colour")}
              htmlFor="group-color"
              hint={t("For the map layer")}
            >
              <div className="flex items-center gap-2">
                <input
                  id="group-color"
                  type="color"
                  className="h-9 w-12 cursor-pointer rounded-md border bg-transparent p-1"
                  value={color || "#52735E"}
                  onChange={(e) => form.setValue("color", e.target.value)}
                />
                {color ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => form.setValue("color", "")}
                  >
                    {t("None")}
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {t("none")}
                  </span>
                )}
              </div>
            </Field>
            <Field
              label={t("Order")}
              htmlFor="group-order"
              hint={t("Lower comes first")}
              error={form.formState.errors.sort_order?.message}
            >
              <Input
                id="group-order"
                type="number"
                {...form.register("sort_order")}
              />
            </Field>
          </div>
          <Field label={t("Description")} htmlFor="group-description">
            <Textarea
              id="group-description"
              rows={2}
              {...form.register("description")}
            />
          </Field>
          {form.formState.errors.root && (
            <Callout kind="error">{form.formState.errors.root.message}</Callout>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {t("Cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? t("Saving…") : t("Save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Folders of entities, two levels deep (decision D98): the lists filter by them and the map
 * shows and hides per group. */
export function GroupsPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const groups = useGroups(projectId);
  const [editing, setEditing] = useState<{
    group: EntityGroup | null;
    parentId: string | null;
  } | null>(null);
  const [removing, setRemoving] = useState<EntityGroup | null>(null);
  const remove = useMutationToast({
    mutationFn: (id: string) =>
      api.delete(`/api/v1/projects/${projectId}/groups/${id}`),
    invalidate: [queryKeys.groups(projectId), queryKeys.entities(projectId)],
    success: t("Group deleted; its entities are ungrouped"),
    onSuccess: () => setRemoving(null),
  });
  const rows = groupTree(groups.data);
  const subgroupsOf = (g: EntityGroup) =>
    (groups.data ?? []).filter((x) => x.parent_id === g.id);
  const totalOf = (g: EntityGroup) =>
    g.entity_count + subgroupsOf(g).reduce((n, x) => n + x.entity_count, 0);
  return (
    <>
      <PageHeader
        title={t("Groups")}
        description={t(
          "Folders of entities: a herd, a team, a region. Two levels deep.",
        )}
        actions={
          <Button onClick={() => setEditing({ group: null, parentId: null })}>
            <Plus className="size-4" /> {t("New group")}
          </Button>
        }
      />
      <Page>
        {groups.isPending && (
          <div className="text-sm text-muted-foreground">{t("Loading…")}</div>
        )}
        {groups.data && rows.length === 0 && (
          <div className="text-sm text-muted-foreground">
            {t(
              "No groups yet. Groups let you filter the lists and show or hide parts of the map.",
            )}
          </div>
        )}
        {rows.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("Name")}</TableHead>
                <TableHead>{t("Entities")}</TableHead>
                <TableHead>{t("Description")}</TableHead>
                <TableHead className="w-32" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ group, depth }) => (
                <TableRow key={group.id}>
                  <TableCell>
                    <span
                      className="inline-flex items-center gap-2"
                      style={{ paddingLeft: depth * 20 }}
                    >
                      <span
                        className="inline-block size-3 rounded-full border"
                        style={{ background: group.color ?? "transparent" }}
                      />
                      <span className={depth === 0 ? "font-medium" : ""}>
                        {group.name}
                      </span>
                    </span>
                  </TableCell>
                  <TableCell>
                    {depth === 0 && subgroupsOf(group).length > 0
                      ? t("{{direct}} here, {{total}} in all", {
                          direct: group.entity_count,
                          total: totalOf(group),
                        })
                      : group.entity_count}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {group.description ?? ""}
                  </TableCell>
                  <TableCell className="text-right">
                    {depth === 0 && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={t("New subgroup")}
                        title={t("New subgroup")}
                        onClick={() =>
                          setEditing({ group: null, parentId: group.id })
                        }
                      >
                        <Plus className="size-4" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("Edit group")}
                      onClick={() => setEditing({ group, parentId: null })}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("Delete group")}
                      onClick={() => setRemoving(group)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Page>
      <GroupDialog
        projectId={projectId}
        group={editing?.group ?? null}
        parentId={editing?.parentId ?? null}
        open={editing != null}
        onOpenChange={(o) => !o && setEditing(null)}
      />
      <ConfirmDialog
        open={removing != null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("Delete group")}
        description={
          removing
            ? t(
                "{{name}} is removed with its {{subgroups}} subgroups; its {{count}} entities stay and become ungrouped.",
                {
                  name: removing.name,
                  subgroups: subgroupsOf(removing).length,
                  count: totalOf(removing),
                },
              )
            : undefined
        }
        confirmLabel={t("Delete")}
        onConfirm={() => removing && remove.mutate(removing.id)}
        pending={remove.isPending}
      />
    </>
  );
}
