import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device } from "@/api/types";
import { Callout } from "@/components/common/Callout";
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
  const [serial, setSerial] = useState(device.serial_number ?? "");
  const trimmed = name.trim();
  const serialTrimmed = serial.trim();
  // an OpenCollar's serial is its DevEUI, sixteen hex digits (decision D101); the card's EUI
  // is never guessed, so a slip in it is corrected here
  const serialBad =
    serialTrimmed !== "" &&
    device.serial_number?.length === 16 &&
    !/^[0-9A-Fa-f]{16}$/.test(serialTrimmed);
  const changed =
    trimmed !== device.name || serialTrimmed !== (device.serial_number ?? "");
  const valid =
    trimmed.length > 0 && trimmed.length <= 200 && !serialBad && changed;
  const save = useMutationToast({
    mutationFn: () =>
      api.patch<Device>(`/api/v1/devices/${device.id}`, {
        body: {
          name: trimmed,
          ...(serialTrimmed !== (device.serial_number ?? "")
            ? { serial_number: serialTrimmed || null }
            : {}),
        },
      }),
    invalidate: [queryKeys.device(device.id), ["devices"], ["projects"]],
    success: (d) =>
      d.serial_number
        ? t("{{name}}, serial {{serial}}, saved", {
            name: d.name,
            serial: d.serial_number,
          })
        : t("The device is called {{name}} now", { name: d.name }),
    onSuccess: () => onOpenChange(false),
    // the refusal stays in the dialog, where the name is corrected; no toast over it
    onError: () => undefined,
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("Edit {{name}}", { name: device.name })}</DialogTitle>
          <DialogDescription>
            {t(
              "The name the lists, the map and the reports show for this device; the label name (SP…) as a rule. The serial number is the DevEUI for an OpenCollar.",
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
        <Field
          label={t("Serial number")}
          htmlFor="device-serial"
          hint={t(
            "For an OpenCollar the DevEUI printed on the device, sixteen hex digits; the cards and the network know the device by it, so it must be exact.",
          )}
          error={serialBad ? t("A DevEUI is sixteen hex digits") : undefined}
        >
          <Input
            id="device-serial"
            className="font-mono"
            value={serial}
            maxLength={128}
            onChange={(e) => setSerial(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        {save.isError && <Callout kind="error">{save.error.message}</Callout>}
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
            {t("Save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
