import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Entity } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { EntityTypeSelect } from "@/components/entities/EntityTypeSelect";
import { GroupSelect } from "@/components/entities/GroupSelect";
import { IconPicker } from "@/components/icons/IconPicker";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useMutationToast } from "@/hooks/useMutationToast";

const schema = z.object({
  name: z.string().min(1, "Give the entity a name").max(200),
  entity_type_id: z.string().min(1, "Choose a type"),
  icon_key: z.string(),
  status: z.enum(["active", "inactive", "archived"]),
  group_id: z.string(),
  latitude: z.string().optional(),
  longitude: z.string().optional(),
  notes: z.string().optional(),
});
type Values = z.infer<typeof schema>;

export function EntityDialog({ projectId, entity, open, onOpenChange }: { projectId: string; entity: Entity | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", entity_type_id: "", icon_key: "", status: "active", group_id: "", latitude: "", longitude: "", notes: "" } });

  useEffect(() => {
    if (!open) return;
    const point = entity?.geometry?.type === "Point" ? (entity.geometry.coordinates as number[]) : null;
    form.reset({
      name: entity?.name ?? "",
      entity_type_id: entity?.entity_type_id ?? "",
      icon_key: entity?.icon_key ?? "",
      status: (entity?.status as Values["status"]) ?? "active",
      group_id: entity?.group_id ?? "",
      latitude: point ? String(point[1]) : "",
      longitude: point ? String(point[0]) : "",
      notes: entity?.notes ?? "",
    });
  }, [open, entity, form]);

  const save = useMutationToast({
    mutationFn: (values: Values) => {
      const geometry = values.latitude && values.longitude ? { type: "Point", coordinates: [Number(values.longitude), Number(values.latitude)] } : null;
      const body = { name: values.name, entity_type_id: values.entity_type_id, icon_key: values.icon_key || null, status: values.status, group_id: values.group_id || null, notes: values.notes || null, geometry };
      return entity ? api.patch<Entity>(`/api/v1/projects/${projectId}/entities/${entity.id}`, { body }) : api.post<Entity>(`/api/v1/projects/${projectId}/entities`, { body });
    },
    invalidate: [queryKeys.entities(projectId), queryKeys.currentState(projectId)],
    success: entity ? "Entity updated" : "Entity created",
    onSuccess: () => onOpenChange(false),
    onError: (error) => form.setError("root", { message: error.message }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{entity ? "Edit entity" : "New entity"}</DialogTitle></DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <Field label={t("Name")} htmlFor="name" error={form.formState.errors.name?.message}>
            <Input id="name" {...form.register("name")} />
          </Field>
          <Field label={t("Type")} htmlFor="entity_type_id" hint={t("The kind of thing, then the species or model; the icon follows the choice")} error={form.formState.errors.entity_type_id?.message}>
            <EntityTypeSelect id="entity_type_id" projectId={projectId} value={form.watch("entity_type_id")} onChange={(v) => form.setValue("entity_type_id", v, { shouldValidate: true })} />
          </Field>
          <Field label={t("Icon")} htmlFor="entity_icon" hint={t("Only when this one entity should look different from its type")}>
            <div className="flex items-center gap-2">
              <IconPicker id="entity_icon" value={form.watch("icon_key")} onChange={(v) => form.setValue("icon_key", v)} className="flex-1" />
              {form.watch("icon_key") && <Button type="button" variant="ghost" size="sm" onClick={() => form.setValue("icon_key", "")}>{t("Use the type's icon")}</Button>}
            </div>
          </Field>
          <Field label={t("Status")} htmlFor="status">
            <Select value={form.watch("status")} onValueChange={(v) => form.setValue("status", v as Values["status"])}>
              <SelectTrigger id="status"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="active">{t("active")}</SelectItem>
                <SelectItem value="inactive">{t("inactive")}</SelectItem>
                <SelectItem value="archived">{t("archived")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label={t("Group")} htmlFor="entity-group">
            <GroupSelect id="entity-group" projectId={projectId} mode="choice" value={form.watch("group_id")} onChange={(v) => form.setValue("group_id", v)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Latitude")} htmlFor="latitude" hint={t("Static location, for infrastructure")}>
              <Input id="latitude" inputMode="decimal" {...form.register("latitude")} />
            </Field>
            <Field label={t("Longitude")} htmlFor="longitude">
              <Input id="longitude" inputMode="decimal" {...form.register("longitude")} />
            </Field>
          </div>
          <Field label={t("Notes")} htmlFor="notes">
            <Textarea id="notes" rows={2} {...form.register("notes")} />
          </Field>
          {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("Cancel")}</Button>
            <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
