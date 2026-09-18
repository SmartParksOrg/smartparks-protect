import { useTranslation } from "react-i18next";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";

const SHAPE = /^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

/**
 * The device's own Bluetooth address (decision D252). It is what lets a neighbour's scan of this
 * device be recognised as this device, since a scan reports only the last three octets, so a
 * device without one can be seen by others and never named. The device tells us itself when it
 * is asked ("Request the Bluetooth address" under Control), which is the way to prefer: an
 * address copied from a label can be wrong, and a wrong one quietly makes every contact of this
 * device unresolvable rather than failing loudly.
 */
export function BleAddress({
  deviceId,
  address,
  canEdit,
}: {
  deviceId: string;
  address: string | null;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(address ?? "");
  const save = useMutationToast({
    mutationFn: (ble_mac: string | null) =>
      api.put<Device>(`/api/v1/devices/${deviceId}/ble-address`, {
        body: { ble_mac },
      }),
    invalidate: [queryKeys.device(deviceId), ["devices"]],
    success: (d) =>
      d.ble_mac ? t("Bluetooth address saved") : t("Bluetooth address cleared"),
    onSuccess: () => setEditing(false),
  });
  const valid = value.trim() === "" || SHAPE.test(value.trim());
  if (!editing)
    return (
      <span className="flex flex-wrap items-center gap-2">
        <span className={address ? "font-mono text-xs" : "text-muted-foreground"}>
          {address ?? t("not known")}
        </span>
        {canEdit && (
          <button
            type="button"
            className="text-xs underline underline-offset-2 hover:text-primary"
            onClick={() => {
              setValue(address ?? "");
              setEditing(true);
            }}
          >
            {address ? t("Change") : t("Set")}
          </button>
        )}
      </span>
    );
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="aa:bb:cc:dd:ee:ff"
        aria-label={t("Bluetooth address")}
        aria-invalid={!valid}
        className="h-7 w-44 font-mono text-xs"
      />
      <Button
        size="sm"
        className="h-7"
        disabled={!valid || save.isPending}
        onClick={() => save.mutate(value.trim() || null)}
      >
        {t("Save")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="h-7"
        onClick={() => setEditing(false)}
      >
        {t("Cancel")}
      </Button>
      {!valid && (
        <span className="text-xs text-destructive">
          {t("Six octets, as aa:bb:cc:dd:ee:ff")}
        </span>
      )}
    </span>
  );
}
