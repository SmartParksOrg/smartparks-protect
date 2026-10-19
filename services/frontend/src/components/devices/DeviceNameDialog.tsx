import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device } from "@/api/types";
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

/**
 * The name of a device, changed on its page (Tim, 2026-10-19: a device added with a slip in
 * its name, SP051830 for SP051890, had no way to be renamed). Whoever manages the device may
 * (decision D337). The serial number, a DevEUI for an OpenCollar, is not touched here.
 */
export function DeviceNameDialog({
  device,
  open,
  onOpenChange,
}: {
  device: Device;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(device.name);
  const trimmed = name.trim();
  const valid =
    trimmed.length > 0 && trimmed.length <= 200 && trimmed !== device.name;
  const save = useMutationToast({
    mutationFn: () =>
      api.patch<Device>(`/api/v1/devices/${device.id}`, {
        body: { name: trimmed },
      }),
    invalidate: [queryKeys.device(device.id), ["devices"], ["projects"]],
    success: (d) => t("The device is called {{name}} now", { name: d.name }),
    onSuccess: () => onOpenChange(false),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("Rename {{name}}", { name: device.name })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "The name the lists, the map and the reports show for this device; the label name (SP…) as a rule. The serial number stays as it is.",
            )}
          </DialogDescription>
        </DialogHeader>
        <Field label={t("Name")} htmlFor="device-name">
          <Input
            id="device-name"
            value={name}
            maxLength={200}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && valid && !save.isPending) save.mutate();
            }}
          />
        </Field>
        {device.serial_number && (
          <p className="text-xs text-muted-foreground">
            {t("Serial number {{serial}}", { serial: device.serial_number })}
          </p>
        )}
        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t("Cancel")}
          </Button>
          <Button
            type="button"
            disabled={!valid || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("Save name")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
