import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "@/api/client";
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
 * Delete a device (Tim, 2026-10-19). A device without data goes on one confirmation. A device
 * with data is refused by the server with its counts; a server admin may then delete it with
 * every message, record and file, after typing DELETE, since nothing brings that back.
 */
export function DeleteDeviceDialog({
  device,
  open,
  serverAdmin,
  onOpenChange,
  onDeleted,
}: {
  device: Device;
  open: boolean;
  serverAdmin: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  // the server's refusal, with the counts: the device has data
  const [hasData, setHasData] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const remove = useMutationToast({
    mutationFn: (withData: boolean) =>
      api.delete<void>(
        `/api/v1/devices/${device.id}${withData ? "?with_data=true" : ""}`,
      ),
    invalidate: [["devices"], ["projects"]],
    success: t("The device is deleted"),
    onSuccess: onDeleted,
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        setHasData(error.message);
      else setHasData(error.message);
    },
  });
  const close = (next: boolean) => {
    if (!next) {
      setHasData(null);
      setTyped("");
    }
    onOpenChange(next);
  };
  const confirmed = typed.trim() === "DELETE";
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("Delete {{name}}?", { name: device.name })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "A device made by mistake goes while it has no data: no message received, no log file, no record. Its identities stay on their networks, unlinked, so they can be given to the right device.",
            )}
          </DialogDescription>
        </DialogHeader>
        {hasData && (
          <Callout kind={serverAdmin ? "warning" : "error"}>{hasData}</Callout>
        )}
        {hasData && serverAdmin && (
          <Field
            label={t("Type DELETE to delete the device with all its data")}
            htmlFor="delete-device-confirm"
            hint={t(
              "Every message, record and file of this device goes, week by week, and nothing brings it back. Retiring the device keeps its history instead.",
            )}
          >
            <Input
              id="delete-device-confirm"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="DELETE"
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        )}
        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" onClick={() => close(false)}>
            {t("Cancel")}
          </Button>
          {hasData && serverAdmin ? (
            <Button
              type="button"
              variant="destructive"
              disabled={!confirmed || remove.isPending}
              onClick={() => remove.mutate(true)}
            >
              {remove.isPending
                ? t("Deleting…")
                : t("Delete with all its data")}
            </Button>
          ) : (
            <Button
              type="button"
              variant="destructive"
              disabled={remove.isPending || hasData !== null}
              onClick={() => remove.mutate(false)}
            >
              {remove.isPending ? t("Deleting…") : t("Delete")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
