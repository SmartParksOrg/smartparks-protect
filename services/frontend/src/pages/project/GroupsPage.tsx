import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { FolderOpen, GripVertical, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Entity,
  EntityGroup,
  EntityType,
  Page as PageType,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { LoadMore } from "@/components/data/LoadMore";
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
import {
  descendantIds,
  groupPath,
  groupTree,
  useGroups,
} from "@/hooks/useGroups";
import { useQuery } from "@tanstack/react-query";
import { StatusBadge } from "@/components/common/StatusBadge";
import { MoveToGroupDialog } from "@/components/entities/MoveToGroupDialog";
import { Icon } from "@/components/icons/Icon";
import { Card, CardContent } from "@/components/ui/card";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePages } from "@/hooks/usePages";

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
  const blocked = group
    ? [group.id, ...descendantIds(groups.data, group.id)]
    : [];
  const parents = groupTree(groups.data).filter(
    (r) => !blocked.includes(r.group.id),
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
            hint={t("A group can hold groups, as deep as the project needs")}
          >
            <Select
              value={form.watch("parent_id") || "none"}
              onValueChange={(v) =>
                form.setValue("parent_id", v === "none" ? "" : v)
              }
            >
              <SelectTrigger id="group-parent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("Top level")}</SelectItem>
                {parents.map(({ group: g, depth }) => (
                  <SelectItem key={g.id} value={g.id}>
                    <span style={{ paddingLeft: depth * 12 }}>{g.name}</span>
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

const ALL = "all";
const NONE = "none";
const DRAG_TYPE = "application/x-entity-ids";

/** Folders of entities, nested as deep as needed (decision D98): the tree on the left, the
 * entities on the right with search, a type filter, selection and "Move to", and drag and drop
 * from a row onto a group as the shortcut. The lists filter by these groups and the map shows
 * and hides per group. */
export function GroupsPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const groups = useGroups(projectId);
  const types = useQuery({
    queryKey: queryKeys.entityTypes,
    queryFn: () =>
      api.get<PageType<EntityType>>("/api/v1/entity-types", {
        query: { limit: 500 },
      }),
  });
  const [node, setNode] = useState(ALL);
  const [q, setQ] = useState("");
  const [typeId, setTypeId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moving, setMoving] = useState<string[] | null>(null);
  const [editing, setEditing] = useState<{
    group: EntityGroup | null;
    parentId: string | null;
  } | null>(null);
  const [removing, setRemoving] = useState<EntityGroup | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const filters = {
    q: q || undefined,
    entity_type_id: typeId || undefined,
    group_id: node !== ALL && node !== NONE ? node : undefined,
    ungrouped: node === NONE ? true : undefined,
    limit: 500,
  };
  const entities = usePages<Entity>({
    queryKey: [...queryKeys.entities(projectId), "organize", filters],
    fetchPage: (cursor) =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { ...filters, cursor },
      }),
    keepPrevious: true,
  });
  const all = useQuery({
    queryKey: [...queryKeys.entities(projectId), "organize", "all"],
    queryFn: () =>
      api.get<PageType<Entity>>(`/api/v1/projects/${projectId}/entities`, {
        query: { limit: 500 },
      }),
  });
  const remove = useMutationToast({
    mutationFn: (id: string) =>
      api.delete(`/api/v1/projects/${projectId}/groups/${id}`),
    invalidate: [queryKeys.groups(projectId), queryKeys.entities(projectId)],
    success: t("Group deleted; its entities are ungrouped"),
    onSuccess: () => {
      setRemoving(null);
      setNode(ALL);
    },
  });
  const drop = useMutationToast({
    mutationFn: ({ ids, groupId }: { ids: string[]; groupId: string | null }) =>
      api.post<{ moved: number }>(
        `/api/v1/projects/${projectId}/entities/bulk-move`,
        { body: { entity_ids: ids, group_id: groupId } },
      ),
    invalidate: [
      queryKeys.entities(projectId),
      queryKeys.groups(projectId),
      queryKeys.currentState(projectId),
      queryKeys.devices({ projectId }),
    ],
    success: (r) => t("{{count}} entities moved", { count: r.moved }),
    onSuccess: () => setSelected(new Set()),
  });
  const tree = groupTree(groups.data);
  const rows = entities.items;
  const typeById = useMemo(
    () => new Map(types.data?.items.map((x) => [x.id, x])),
    [types.data],
  );
  const totalOf = (g: EntityGroup) =>
    g.entity_count +
    descendantIds(groups.data, g.id).reduce(
      (n, id) => n + (groups.data?.find((x) => x.id === id)?.entity_count ?? 0),
      0,
    );
  const grouped = (groups.data ?? []).reduce((n, g) => n + g.entity_count, 0);
  const total = all.data
    ? all.data.next_cursor
      ? "500+"
      : String(all.data.items.length)
    : "";
  const ungrouped =
    all.data && !all.data.next_cursor
      ? String(all.data.items.length - grouped)
      : "";
  const allShownSelected =
    rows.length > 0 && rows.every((e) => selected.has(e.id));
  const toggleAll = (on: boolean) =>
    setSelected(on ? new Set(rows.map((e) => e.id)) : new Set());
  const toggleOne = (id: string, on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const onDragStart = (e: React.DragEvent, id: string) => {
    e.dataTransfer.setData(
      DRAG_TYPE,
      JSON.stringify(selected.has(id) ? [...selected] : [id]),
    );
    e.dataTransfer.effectAllowed = "move";
  };
  const dropProps = (key: string, groupId: string | null) => ({
    onDragOver: (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes(DRAG_TYPE)) {
        e.preventDefault();
        setDropTarget(key);
      }
    },
    onDragLeave: () => setDropTarget((d) => (d === key ? null : d)),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const raw = e.dataTransfer.getData(DRAG_TYPE);
      if (!raw) return;
      const ids = JSON.parse(raw) as string[];
      if (ids.length > 0) drop.mutate({ ids, groupId });
    },
  });
  const treeRow = (
    key: string,
    label: React.ReactNode,
    count: string | number,
    depth: number,
    groupId: string | null,
    actions?: React.ReactNode,
  ) => (
    <div
      key={key}
      className={`group flex h-9 items-center gap-1.5 rounded-md pr-1 ${node === key ? "bg-primary/10" : "hover:bg-muted"} ${dropTarget === key ? "ring-2 ring-primary" : ""}`}
      style={{ paddingLeft: 6 + depth * 16 }}
      {...dropProps(key, groupId)}
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
        onClick={() => {
          setNode(key);
          setSelected(new Set());
        }}
      >
        {label}
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          {count}
        </span>
      </button>
      {actions && (
        <span className="hidden shrink-0 gap-0.5 group-hover:flex">
          {actions}
        </span>
      )}
    </div>
  );
  return (
    <>
      <PageHeader
        title={t("Groups")}
        description={t(
          "Organize the entities: a region, a herd inside it, a family inside that. Drag entities onto a group, or select them and move.",
        )}
        actions={
          <Button onClick={() => setEditing({ group: null, parentId: null })}>
            <Plus className="size-4" /> {t("New group")}
          </Button>
        }
      />
      <Page>
        <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
          <Card>
            <CardContent className="p-2">
              {treeRow(
                ALL,
                <span className="inline-flex items-center gap-2 font-medium">
                  <FolderOpen className="size-4 text-muted-foreground" />{" "}
                  {t("All entities")}
                </span>,
                total,
                0,
                null,
              )}
              {tree.map(({ group, depth }) =>
                treeRow(
                  group.id,
                  <span className="inline-flex min-w-0 items-center gap-2">
                    <span
                      className="inline-block size-3 shrink-0 rounded-full border"
                      style={{ background: group.color ?? "transparent" }}
                    />
                    <span
                      className={`truncate ${depth === 0 ? "font-medium" : ""}`}
                    >
                      {group.name}
                    </span>
                  </span>,
                  totalOf(group),
                  depth + 1,
                  group.id,
                  <>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={t("New subgroup")}
                      title={t("New subgroup")}
                      onClick={() =>
                        setEditing({ group: null, parentId: group.id })
                      }
                    >
                      <Plus className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={t("Edit group")}
                      title={t("Edit group")}
                      onClick={() => setEditing({ group, parentId: null })}
                    >
                      <Pencil className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={t("Delete group")}
                      title={t("Delete group")}
                      onClick={() => setRemoving(group)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </>,
                ),
              )}
              {treeRow(
                NONE,
                <span className="text-muted-foreground">{t("Ungrouped")}</span>,
                ungrouped,
                1,
                null,
              )}
              {tree.length === 0 && (
                <div className="px-2 py-3 text-xs text-muted-foreground">
                  {t("No groups yet. Create one, then drag entities onto it.")}
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-3 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t("Search by name")}
                  className="h-9 w-56"
                  aria-label={t("Search entities")}
                />
                <Select
                  value={typeId || ALL}
                  onValueChange={(v) => setTypeId(v === ALL ? "" : v)}
                >
                  <SelectTrigger
                    className="h-9 w-44"
                    aria-label={t("Entity type")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>{t("All types")}</SelectItem>
                    {types.data?.items.map((x) => (
                      <SelectItem key={x.id} value={x.id}>
                        {x.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="ml-auto flex items-center gap-2">
                  {selected.size > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {t("{{count}} selected", { count: selected.size })}
                    </span>
                  )}
                  <Button
                    size="sm"
                    disabled={selected.size === 0}
                    onClick={() => setMoving([...selected])}
                  >
                    {t("Move to…")}
                  </Button>
                </span>
              </div>
              {entities.isPending && (
                <div className="text-sm text-muted-foreground">
                  {t("Loading…")}
                </div>
              )}
              {entities.loaded && rows.length === 0 && (
                <div className="text-sm text-muted-foreground">
                  {t("No entities here.")}
                </div>
              )}
              {rows.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8">
                        <input
                          type="checkbox"
                          className="size-4 accent-primary"
                          aria-label={t("Select all rows shown")}
                          checked={allShownSelected}
                          onChange={(e) => toggleAll(e.target.checked)}
                        />
                      </TableHead>
                      <TableHead className="w-6" />
                      <TableHead>{t("Name")}</TableHead>
                      <TableHead>{t("Type")}</TableHead>
                      <TableHead>{t("Group")}</TableHead>
                      <TableHead>{t("Status")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((e) => (
                      <TableRow
                        key={e.id}
                        draggable
                        onDragStart={(ev) => onDragStart(ev, e.id)}
                        className={`cursor-grab ${selected.has(e.id) ? "bg-primary/5" : ""}`}
                      >
                        <TableCell>
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={e.name}
                            checked={selected.has(e.id)}
                            onChange={(ev) =>
                              toggleOne(e.id, ev.target.checked)
                            }
                          />
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          <GripVertical className="size-4" />
                        </TableCell>
                        <TableCell>
                          <Link
                            className="inline-flex items-center gap-2 hover:underline"
                            to={`/projects/${projectId}/entities/${e.id}`}
                          >
                            <Icon
                              iconKey={
                                e.icon_key ??
                                typeById.get(e.entity_type_id)?.icon_key
                              }
                              className="size-4"
                            />
                            {e.name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          {typeById.get(e.entity_type_id)?.label ?? ""}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {groupPath(groups.data, e.group_id) || t("none")}
                        </TableCell>
                        <TableCell>
                          <StatusBadge value={e.status} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <LoadMore
                count={rows.length}
                hasMore={entities.hasMore}
                isLoading={entities.isLoadingMore}
                onLoadMore={entities.loadMore}
              />
            </CardContent>
          </Card>
        </div>
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
                  subgroups: descendantIds(groups.data, removing.id).length,
                  count: totalOf(removing),
                },
              )
            : undefined
        }
        confirmLabel={t("Delete")}
        onConfirm={() => removing && remove.mutate(removing.id)}
        pending={remove.isPending}
      />
      <MoveToGroupDialog
        projectId={projectId}
        entityIds={moving ?? []}
        open={moving != null}
        onOpenChange={(o) => !o && setMoving(null)}
        onMoved={() => setSelected(new Set())}
      />
    </>
  );
}
