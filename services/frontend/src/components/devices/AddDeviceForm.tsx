import { useQuery } from "@tanstack/react-query";
import { Bluetooth, PenLine } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  DeviceLogFile,
  DeviceType,
  DriverCatalog,
  Page as PageType,
  ProjectDeviceCreate,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMutationToast } from "@/hooks/useMutationToast";
import {
  type Catalog,
  connectWebBluetooth,
  type DeviceIdentity,
  hex,
  OpenCollarSession,
  readIdentity,
  webBluetoothAvailable,
} from "@/lib/opencollar-ble";

const EUI = /^[0-9A-Fa-f]{16}$/;

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * A device added inside the project (decision D326, Tim, 2026-10-16), the first step of "Make an
 * offload station" when the RangerEdge is not a device yet (Tim, the same day: adding the device
 * is part of making a station, not a button of its own). Two ways: over Bluetooth, where the
 * hardware itself gives its name, DevEUI, hardware type, firmware and LP0 credentials (read in
 * this browser through the driver's catalogue and saved on the device in the same call; the
 * frames synced as a Bluetooth log for provenance), or by hand. Only OpenCollar device types are
 * offered, and the choice shows only when the server has more than one (Tim: no irrelevant
 * options here). The caller hears what was made and carries on with it.
 */
export function AddDeviceForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (device: Device) => void;
}) {
  const { t } = useTranslation();
  const bluetooth = webBluetoothAvailable();
  const [mode, setMode] = useState<"bluetooth" | "manual">(bluetooth ? "bluetooth" : "manual");
  const types = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", { query: { limit: 500 } }),
  });
  const openCollar = (types.data?.items ?? []).filter((x) => x.driver_key === "opencollar");
  const [chosenTypeId, setChosenTypeId] = useState("");
  const typeId =
    (openCollar.some((x) => x.id === chosenTypeId) ? chosenTypeId : "") || openCollar[0]?.id || "";
  const catalog = useQuery({
    queryKey: [...queryKeys.deviceTypes, typeId, "driver-catalog"],
    queryFn: () => api.get<DriverCatalog>(`/api/v1/device-types/${typeId}/driver-catalog`),
    enabled: Boolean(typeId) && mode === "bluetooth",
  });
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [identity, setIdentity] = useState<DeviceIdentity | null>(null);
  const [reading, setReading] = useState<"idle" | "busy" | "failed">("idle");
  const [readError, setReadError] = useState("");
  const [attempted, setAttempted] = useState(false);
  // the Bluetooth session lives as long as the form: its frames are synced to the device once
  // it exists, then it is closed
  const session = useRef<OpenCollarSession | null>(null);
  useEffect(
    () => () => {
      void session.current?.disconnect();
      session.current = null;
    },
    [],
  );
  const serialBad = serial.trim() !== "" && !EUI.test(serial.trim());
  const missing = !typeId ? "type" : !name.trim() ? "name" : serialBad ? "serial" : null;
  // a station is a RangerEdge; another hardware read here is most likely a tracker picked by mistake
  const notAStation = identity?.hardwareKey != null && identity.hardwareKey !== "rangeredge";

  const read = async () => {
    if (!catalog.data) return;
    setReading("busy");
    setReadError("");
    try {
      await session.current?.disconnect();
      const transport = await connectWebBluetooth();
      const active = new OpenCollarSession(transport);
      session.current = active;
      const status = await active.requestStatus().catch(() => null);
      const values = await active.requestSettings();
      const found = readIdentity(catalog.data.catalog as unknown as Catalog, values, status, active.name);
      setIdentity(found);
      setName(found.name);
      setSerial(found.eui ?? "");
      setReading("idle");
    } catch (error) {
      setReading("failed");
      setReadError(describe(error));
    }
  };

  const create = useMutationToast({
    mutationFn: async () => {
      // the server fills the location fields with their defaults
      const body: Omit<ProjectDeviceCreate, "location_source" | "location_fallback_hours"> = {
        device_type_id: typeId,
        status: "active",
        name: name.trim(),
        serial_number: serial.trim() || null,
        firmware_version: identity?.firmwareVersion ?? null,
        attributes: identity
          ? { hardware_type: identity.hardwareKey, onboarded: "bluetooth" }
          : {},
        lp0: identity?.lp0
          ? {
              dev_addr: identity.lp0.devAddr,
              app_s_key: identity.lp0.appSKey,
              nwk_s_key: identity.lp0.nwkSKey,
              source: "device",
            }
          : null,
      };
      const device = await api.post<Device>(`/api/v1/projects/${projectId}/devices`, { body });
      const active = session.current;
      if (active) {
        const frames = active.takeReceived();
        if (frames.length > 0) {
          try {
            await api.post<DeviceLogFile>(`/api/v1/devices/${device.id}/log-files/ble-sync`, {
              body: {
                frames: frames.map((f) => hex(f.raw)),
                ble_synced_at: frames[frames.length - 1].at.toISOString(),
                label: "onboarding",
                attributes: { device_name: active.name, user_agent: navigator.userAgent },
              },
            });
          } catch (error) {
            toast.error(
              t("The device is made, but the Bluetooth frames could not be synced: {{error}}", {
                error: describe(error),
              }),
            );
          }
        }
        await active.disconnect();
        session.current = null;
      }
      return device;
    },
    invalidate: [
      queryKeys.devices({}),
      queryKeys.projectOffload(projectId),
      queryKeys.entities(projectId),
    ],
    success: (device) =>
      identity?.lp0
        ? t("{{name}} is a device of the project, with its LP0 address and keys", {
            name: device.name,
          })
        : t("{{name}} is a device of the project", { name: device.name }),
    onSuccess: (device) => onCreated(device),
  });

  return (
    <>
      <div className="min-w-0 space-y-4">
        <Tabs value={mode} onValueChange={(v) => setMode(v as "bluetooth" | "manual")}>
          <TabsList>
            <TabsTrigger value="bluetooth" disabled={!bluetooth}>
              <Bluetooth className="size-4" /> {t("Over Bluetooth")}
            </TabsTrigger>
            <TabsTrigger value="manual">
              <PenLine className="size-4" /> {t("By hand")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {!bluetooth && (
          <Callout kind="info">
            {t("Web Bluetooth needs Chrome or Edge over HTTPS; this browser has none, so the device is added by hand.")}
          </Callout>
        )}
        {types.data && openCollar.length === 0 && (
          <Callout kind="warning">
            {t(
              "This server has no OpenCollar device type yet; a server admin adds one under Server admin, Device types.",
            )}
          </Callout>
        )}
        {openCollar.length > 1 && (
          <Field
            label={t("Device type")}
            htmlFor="add-device-type"
            hint={t("The OpenCollar types of this server; a RangerEdge is one of them.")}
            error={attempted && missing === "type" ? t("Choose a device type") : undefined}
          >
            <Select value={typeId} onValueChange={setChosenTypeId}>
              <SelectTrigger id="add-device-type">
                <SelectValue placeholder={t("Choose a device type")} />
              </SelectTrigger>
              <SelectContent>
                {openCollar.map((x) => (
                  <SelectItem key={x.id} value={x.id}>
                    {x.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        {mode === "bluetooth" && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={read}
                disabled={reading === "busy" || !catalog.data}
              >
                <Bluetooth className="size-4" />{" "}
                {reading === "busy"
                  ? t("Reading…")
                  : identity
                    ? t("Read another device")
                    : t("Connect and read")}
              </Button>
              <span className="text-xs text-muted-foreground">
                {t("Hold the device near this computer; the browser asks which one to connect to.")}
              </span>
            </div>
            {reading === "failed" && <Callout kind="error">{readError}</Callout>}
            {identity && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-md border p-3 text-sm">
                <dt className="text-muted-foreground">{t("DevEUI")}</dt>
                <dd className="font-mono">
                  {identity.eui ?? <span className="text-destructive">{t("not reported")}</span>}
                </dd>
                <dt className="text-muted-foreground">{t("Hardware")}</dt>
                <dd>
                  {identity.hardwareKey ??
                    (identity.hardwareType != null
                      ? t("type {{type}}", { type: identity.hardwareType })
                      : t("unknown"))}
                  {identity.firmwareVersion &&
                    `, ${t("firmware {{version}}", { version: identity.firmwareVersion })}`}
                </dd>
                <dt className="text-muted-foreground">{t("LP0 credentials")}</dt>
                <dd>
                  {identity.lp0 ? (
                    <>
                      <span className="font-mono">{identity.lp0.devAddr}</span>
                      {", "}
                      {t("both keys read; they are saved on the device")}
                    </>
                  ) : (
                    <span className="text-destructive">
                      {t("not set on the device; set them later under LP0 offload on its page")}
                    </span>
                  )}
                </dd>
              </dl>
            )}
          </div>
        )}
        {(mode === "manual" || identity) && (
          <>
            <Field
              label={t("Name")}
              htmlFor="add-device-name"
              error={attempted && missing === "name" ? t("Give the device a name") : undefined}
            >
              <Input id="add-device-name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field
              label={t("Serial number")}
              htmlFor="add-device-serial"
              hint={t("The DevEUI, sixteen hex digits: an offload station names the card's files after it.")}
              error={attempted && missing === "serial" ? t("A DevEUI is sixteen hex digits") : undefined}
            >
              <Input
                id="add-device-serial"
                className="font-mono"
                value={serial}
                onChange={(e) => setSerial(e.target.value)}
              />
            </Field>
            {notAStation && (
              <Callout kind="warning">
                {t(
                  "The device says it is a {{hardware}}, not a RangerEdge. An offload station is a RangerEdge with an SD card; a tracker gets its LP0 address and keys from this read all the same.",
                  { hardware: identity?.hardwareKey ?? "" },
                )}
              </Callout>
            )}
          </>
        )}
        {create.isError && <Callout kind="error">{create.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button
          type="button"
          disabled={create.isPending || !typeId || (mode === "bluetooth" && !identity)}
          onClick={() => (missing === null ? create.mutate() : setAttempted(true))}
        >
          {create.isPending ? t("Adding…") : t("Add the device and continue")}
        </Button>
      </DialogFooter>
    </>
  );
}
