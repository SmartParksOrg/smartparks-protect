import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { Gateway } from "@/api/types";
import { Field } from "@/components/common/FormField";
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
import { useMutationToast } from "@/hooks/useMutationToast";

/** The name a person gives a gateway (decision D247): the platform's own name is often the
 * gateway id or a name nobody in the field recognises, and the name is what the lists, the map
 * and the reports show. An empty name gives the platform's back. */
export function GatewayNameDialog({
  projectId,
  gateway,
  onClose,
}: {
  projectId: string;
  gateway: Gateway | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(gateway?.name_override ?? "");
  const platformName = gateway?.name ?? gateway?.external_id ?? "";
  const save = useMutationToast({
    mutationFn: (body: { name: string | null }) =>
      api.patch<Gateway>(
        `/api/v1/projects/${projectId}/gateways/${gateway?.id}`,
        { body },
      ),
    invalidate: [["projects", projectId, "gateways"]],
    success: t("Gateway name saved"),
    onSuccess: onClose,
  });
  return (
    <Dialog open={gateway !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("Name of {{name}}", { name: gateway?.display_name ?? "" })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "The name this gateway carries in the lists, on the map and in the reports. Leave it empty to use the name the network gives it.",
            )}
          </DialogDescription>
        </DialogHeader>
        <Field label={t("Name")} htmlFor="gw-name">
          <Input
            id="gw-name"
            value={name}
            maxLength={200}
            placeholder={platformName}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !save.isPending)
                save.mutate({ name: name.trim() || null });
            }}
          />
        </Field>
        <p className="text-xs text-muted-foreground">
          {t("The network calls it {{name}}.", { name: platformName })}
        </p>
        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={save.isPending}
            onClick={() => save.mutate({ name: name.trim() || null })}
          >
            {t("Save name")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
