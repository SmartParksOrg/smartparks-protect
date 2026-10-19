import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  Lp0Credentials,
  OffloadStationSetupResult,
  OffloadUnknownAddress,
  Page as PageType,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { AddDeviceForm } from "@/components/devices/AddDeviceForm";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";

const KEY = /^[0-9A-Fa-f]{32}$/;
const clean = (text: string) => text.replace(/[\s:_-]/g, "");

/**
 * An address the stations received that no device has, made into a device (decision D338,
 * Tim, 2026-10-19: the trackers may not be known to Protect yet when a card arrives). Two ways:
 * a new device, the form of the station dialog with the address, the DevEUI the card named
 * and a name filled in, read over Bluetooth or typed; or a device of the project that has no
 * LP0 address yet, which takes the address and, when known, the keys. Either way the frames
 * stored for the address become the device's and are decoded as soon as the keys are set.
 */
export function AddTrackerDialog({
  projectId,
  address,
  onOpenChange,
}: {
  projectId: string;
  /** The row to add; nothing closes the dialog. */
  address: OffloadUnknownAddress | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={address !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("Add the device")}</DialogTitle>
          <DialogDescription>
            {address && <KindWords address={address} />}
          </DialogDescription>
        </DialogHeader>
        {address && (
          <TrackerForm
            projectId={projectId}
            address={address}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Mounted while the dialog is open, so every opening starts afresh. */
function TrackerForm({
  projectId,
  address,
  onDone,
}: {
  projectId: string;
  address: OffloadUnknownAddress;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  // the first decision (decision D341): a station, when its frames are the status reports a
  // station sends of itself (port 23), or a tracker, when they are a stored stream (port 29);
  // the ports say which is likely, the person decides
  const [kind, setKind] = useState<"tracker" | "station">(
    address.kind_hint === "station" ? "station" : "tracker",
  );
  const [way, setWay] = useState<"new" | "existing">("new");
  const makeStation = useMutationToast({
    mutationFn: (device: Device) =>
      api.post<OffloadStationSetupResult>(
        `/api/v1/projects/${projectId}/offload/stations`,
        {
          body: { device_id: device.id },
        },
      ),
    invalidate: [
      queryKeys.projectOffload(projectId),
      queryKeys.entities(projectId),
    ],
    success: (r) =>
      t(
        "{{device}} is an offload station now, as the entity {{entity}}; set its place on its page",
        {
          device: r.device_name,
          entity: r.entity_name,
        },
      ),
    onSuccess: onDone,
  });
  const [deviceId, setDeviceId] = useState("");
  const [q, setQ] = useState("");
  const [appKey, setAppKey] = useState("");
  const [nwkKey, setNwkKey] = useState("");
  const [attempted, setAttempted] = useState(false);
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, limit: 500 }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
    enabled: way === "existing",
  });
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const items = devices.data?.items ?? [];
    return needle
      ? items.filter(
          (d) =>
            d.name.toLowerCase().includes(needle) ||
            (d.serial_number ?? "").toLowerCase().includes(needle),
        )
      : items;
  }, [devices.data, q]);
  const keysHalf = (clean(appKey) === "") !== (clean(nwkKey) === "");
  const keysBad =
    (clean(appKey) !== "" && !KEY.test(clean(appKey))) ||
    (clean(nwkKey) !== "" && !KEY.test(clean(nwkKey)));
  const missing = !deviceId ? "device" : keysHalf || keysBad ? "keys" : null;
  const link = useMutationToast({
    mutationFn: () =>
      api.put<Lp0Credentials & { queued: number }>(
        `/api/v1/devices/${deviceId}/lp0-credentials`,
        {
          body: {
            dev_addr: address.dev_addr,
            ...(clean(appKey) !== ""
              ? { app_s_key: clean(appKey), nwk_s_key: clean(nwkKey) }
              : {}),
          },
        },
      ),
    invalidate: [
      queryKeys.projectOffload(projectId),
      queryKeys.lp0Credentials(deviceId),
      queryKeys.device(deviceId),
      ["attention"],
    ],
    success: (r) =>
      r.keys_set
        ? t(
            "The address and keys are set; {{count}} waiting frames handed to the decoder",
            {
              count: r.queued,
            },
          )
        : t(
            "The address is the device's now; {{count}} frames wait for its keys",
            {
              count: r.frames_waiting,
            },
          ),
    onSuccess: onDone,
  });
  const suggestedName = address.dev_eui ?? `LP0 ${address.dev_addr}`;
  return (
    <div className="min-w-0 space-y-4">
      <Field
        label={t("What is it?")}
        htmlFor="tracker-kind"
        hint={
          address.kind_hint === "station"
            ? t(
                "Its frames are the status reports a station sends of itself (port 23): most likely an offload station.",
              )
            : address.kind_hint === "tracker"
              ? t(
                  "Its frames are a stored stream (port 29): most likely a tracker.",
                )
              : t(
                  "Its frames say nothing certain; choose what the hardware is.",
                )
        }
      >
        <RadioGroup
          id="tracker-kind"
          value={kind}
          onValueChange={(v) => setKind(v as "tracker" | "station")}
          className="flex flex-wrap gap-x-6 gap-y-2"
        >
          <label className="flex items-center gap-2 text-sm">
            <RadioGroupItem value="tracker" /> {t("A tracker")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <RadioGroupItem value="station" /> {t("An offload station")}
          </label>
        </RadioGroup>
      </Field>
      <Tabs value={way} onValueChange={(v) => setWay(v as "new" | "existing")}>
        <TabsList>
          <TabsTrigger value="new">{t("A new device")}</TabsTrigger>
          <TabsTrigger value="existing">
            {t("A device of the project")}
          </TabsTrigger>
        </TabsList>
      </Tabs>
      {way === "new" ? (
        <AddDeviceForm
          projectId={projectId}
          initial={{
            name: suggestedName,
            serial: address.dev_eui ?? "",
            lp0Address: address.dev_addr,
          }}
          onCreated={(device) =>
            kind === "station" ? makeStation.mutate(device) : onDone()
          }
        />
      ) : (
        <>
          <Field
            label={t("Device")}
            htmlFor="tracker-device-search"
            hint={t(
              "A device of this project without an LP0 address yet: the address becomes its.",
            )}
            error={
              attempted && missing === "device"
                ? t("Pick a device from the list")
                : undefined
            }
          >
            <Input
              id="tracker-device-search"
              placeholder={t("Search by name or serial")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </Field>
          <div
            className="max-h-48 overflow-y-auto rounded-md border"
            role="listbox"
            aria-label={t("Devices")}
          >
            {devices.isPending && (
              <div className="p-3 text-sm text-muted-foreground">
                {t("Loading devices…")}
              </div>
            )}
            {devices.data && shown.length === 0 && (
              <div className="p-3 text-sm text-muted-foreground">
                {q
                  ? t("No device matches.")
                  : t("No devices in this project yet.")}
              </div>
            )}
            {shown.map((d) => (
              <button
                key={d.id}
                type="button"
                role="option"
                aria-selected={d.id === deviceId}
                className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted ${d.id === deviceId ? "bg-muted" : ""}`}
                onClick={() => setDeviceId(d.id)}
              >
                <span className="font-medium">{d.name}</span>
                {d.serial_number && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {d.serial_number}
                  </span>
                )}
              </button>
            ))}
          </div>
          <Field
            label={t("Session keys")}
            htmlFor="tracker-app-key"
            hint={t(
              "AppSKey and NwkSKey as provisioned on the device, 32 hex digits each. Leave both empty to set them later on the device page; the frames wait until then.",
            )}
            error={
              attempted && missing === "keys"
                ? t("Give both keys of 32 hex digits, or neither")
                : undefined
            }
          >
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                id="tracker-app-key"
                className="font-mono"
                placeholder="AppSKey"
                value={appKey}
                onChange={(e) => setAppKey(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
              <Input
                className="font-mono"
                placeholder="NwkSKey"
                aria-label="NwkSKey"
                value={nwkKey}
                onChange={(e) => setNwkKey(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          </Field>
          {link.isError && <Callout kind="error">{link.error.message}</Callout>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onDone}>
              {t("Cancel")}
            </Button>
            <Button
              type="button"
              disabled={link.isPending}
              onClick={() =>
                missing === null ? link.mutate() : setAttempted(true)
              }
            >
              {link.isPending ? t("Saving…") : t("Give it the address")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

/** What the stations heard of the address, and what the ports say it is (decision D341). */
function KindWords({ address }: { address: OffloadUnknownAddress }) {
  const { t } = useTranslation();
  const heard = t(
    "The stations received {{frames}} frames of LP0 address {{address}}",
    {
      frames: address.receptions,
      address: address.dev_addr,
    },
  );
  const named = address.dev_eui
    ? t("; the card names the device {{eui}}.", { eui: address.dev_eui })
    : t(", and the card does not name the device.");
  return (
    <>
      {heard}
      {named}{" "}
      {t(
        "Give it the name from its label (SP…) when you know it, or read the device over Bluetooth, which brings the name, the DevEUI and the keys. The DevEUI is never guessed.",
      )}
    </>
  );
}
