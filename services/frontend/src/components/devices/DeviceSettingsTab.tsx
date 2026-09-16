import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Bluetooth, Check, Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  ActionAvailability,
  CommandItem,
  DeviceSetting,
  DeviceSettings,
} from "@/api/types";
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
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { useWebBle } from "@/hooks/useWebBle";
import { formatAgo } from "@/lib/format";

const SOURCE_LABELS: Record<string, string> = {
  frame: "the collar reported it",
  ble: "read over Bluetooth",
  command: "sent by Protect",
  manual: "entered by a person",
};

/** A setting's value as words, with its unit. */
function showValue(s: DeviceSetting, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (s.type === "bool") return value ? "on" : "off";
  if (s.type === "byte_array" || s.type === "string") return String(value);
  const n = Number(value);
  if (s.unit === "s" && n >= 3600 && n % 3600 === 0) return `${n / 3600} h`;
  if (s.unit === "s" && n >= 60 && n % 60 === 0) return `${n / 60} min`;
  return s.unit ? `${n} ${s.unit}` : String(n);
}

/**
 * The Settings tab of a device (decisions D228 to D231): every setting of the type's
 * catalogue, grouped, with the value Protect knows, where it came from and when; unknown
 * ones greyed. "Request all settings" asks the collar to report them, "Set" sends a new
 * value through the command pipeline, "Record" keeps a value a person knows without sending.
 */
export function DeviceSettingsTab({
  deviceId,
  canControl,
  canRecord,
}: {
  deviceId: string;
  canControl: boolean;
  canRecord: boolean;
}) {
  const { t } = useTranslation();
  const settings = useQuery({
    queryKey: queryKeys.deviceSettings(deviceId),
    queryFn: () =>
      api.get<DeviceSettings>(`/api/v1/devices/${deviceId}/settings`),
    refetchInterval: 30_000,
  });
  const actions = useQuery({
    queryKey: queryKeys.deviceActions(deviceId),
    queryFn: () =>
      api.get<ActionAvailability[]>(`/api/v1/devices/${deviceId}/actions`),
    enabled: canControl,
  });
  const [filter, setFilter] = useState("");
  const [unknownToo, setUnknownToo] = useState(true);
  const [editing, setEditing] = useState<DeviceSetting | null>(null);
  // a collar connected in this browser reports its whole table over Bluetooth for free;
  // over LoRaWAN or satellite a full report costs power and arrives in one part only
  const ble = useWebBle(deviceId);
  const readAll = useMutationToast({
    mutationFn: async () => {
      const session = ble.session;
      if (!session)
        throw new Error(t("The collar is not connected over Bluetooth"));
      const values = await session.requestSettings();
      await ble.sync("settings", session);
      return values.size;
    },
    success: (n: number) =>
      t(
        "{{count}} settings read over Bluetooth; they are decoded in the background",
        { count: n },
      ),
    invalidate: [queryKeys.deviceSettings(deviceId)],
  });
  const request = useMutationToast({
    mutationFn: () =>
      api.post<CommandItem>(`/api/v1/devices/${deviceId}/commands`, {
        body: {
          action_key: "REQUEST_SETTINGS",
          parameters: {},
          confirmed: true,
        },
      }),
    success: t(
      "The collar is asked for its settings; they fill in as they arrive.",
    ),
    invalidate: [queryKeys.deviceCommands(deviceId)],
  });
  const available = new Set(
    (actions.data ?? []).filter((a) => a.available).map((a) => a.key),
  );
  const s = settings.data;
  const rows = (s?.items ?? []).filter(
    (row) =>
      (unknownToo || row.value !== null) &&
      (!filter ||
        row.key.includes(filter.toLowerCase()) ||
        (row.description ?? "").toLowerCase().includes(filter.toLowerCase()) ||
        (row.group ?? "").toLowerCase().includes(filter.toLowerCase())),
  );
  const groups = [...new Set(rows.map((r) => r.group ?? "Other"))].sort();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder={t("Filter settings")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8 max-w-xs"
        />
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={unknownToo} onCheckedChange={setUnknownToo} />
          {t("Show unknown settings")}
        </label>
        <span className="text-xs text-muted-foreground">
          {s &&
            t(
              "{{known}} of {{total}} known; catalogue of firmware {{firmware}}",
              {
                known: s.known,
                total: s.items.length,
                firmware: s.firmware ?? "?",
              },
            )}
          {s?.device_firmware &&
            ` · ${t("device firmware {{v}}", { v: s.device_firmware })}`}
        </span>
        {ble.session ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={readAll.isPending}
            onClick={() => readAll.mutate()}
          >
            <Bluetooth className="size-4" />{" "}
            {t("Read all settings over Bluetooth")}
          </Button>
        ) : (
          canControl &&
          available.has("REQUEST_SETTINGS") && (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              disabled={request.isPending}
              title={t(
                "Over LoRaWAN or satellite a full report costs the collar power and only the first part arrives; connect it over Bluetooth on the Data tab to read everything, or ask for one setting at a time with the pencil.",
              )}
              onClick={() => request.mutate()}
            >
              <RefreshCw className="size-4" /> {t("Request all settings")}
            </Button>
          )
        )}
      </div>
      {!ble.session && (
        <p className="text-xs text-muted-foreground">
          {t(
            "A collar connected over Bluetooth (Data tab) reports its whole table at no cost. Over LoRaWAN or satellite, ask for one setting at a time with the pencil: a full report costs the collar power and only its first part arrives.",
          )}
        </p>
      )}
      {settings.isError && (
        <Callout kind="error">{settings.error.message}</Callout>
      )}
      {s && s.items.length === 0 && (
        <Callout kind="info">
          {t("This device type's driver publishes no settings catalogue.")}
        </Callout>
      )}
      {groups.map((group) => (
        <div key={group} className="rounded-md border">
          <div className="border-b bg-muted/40 px-3 py-1.5 text-sm font-medium">
            {group}
          </div>
          <div className="text-sm">
            {rows
              .filter((r) => (r.group ?? "Other") === group)
              .map((row) => {
                const known = row.value !== null && row.value !== undefined;
                return (
                  <div
                    key={row.key}
                    className={`grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 border-t px-3 py-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.6fr)_auto] sm:items-start ${known ? "" : "text-muted-foreground"}`}
                  >
                    <div className="min-w-0 sm:col-start-1 sm:row-start-1">
                      <div className="font-mono text-xs break-all">
                        {row.key}
                      </div>
                      {row.description && (
                        <div className="text-xs text-muted-foreground">
                          {row.description}
                        </div>
                      )}
                    </div>
                    <div className="col-start-2 row-start-1 sm:col-start-4">
                      {(canControl || canRecord) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(row)}
                          aria-label={t("Change {{setting}}", {
                            setting: row.key,
                          })}
                        >
                          <Pencil className="size-4" />
                        </Button>
                      )}
                    </div>
                    <div className="col-span-2 tabular-nums sm:col-span-1 sm:col-start-2 sm:row-start-1 sm:pt-1">
                      {known ? (
                        <span className={row.status === "sent" ? "italic" : ""}>
                          {showValue(row, row.value)}
                        </span>
                      ) : (
                        <span className="text-xs">{t("unknown")}</span>
                      )}
                    </div>
                    <div className="col-span-2 text-xs text-muted-foreground sm:col-span-1 sm:col-start-3 sm:row-start-1 sm:pt-1">
                      {known ? (
                        <>
                          {t(
                            SOURCE_LABELS[row.source ?? ""] ?? row.source ?? "",
                          )}
                          {row.status === "sent" &&
                            ` · ${t("not yet confirmed")}`}
                          {row.observed_at &&
                            ` · ${formatAgo(row.observed_at)}`}
                        </>
                      ) : (
                        <>
                          {t("default {{value}}", {
                            value: showValue(row, row.default) || "–",
                          })}
                          {row.since_firmware &&
                            ` · ${t("since firmware {{v}}", { v: row.since_firmware })}`}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      ))}
      <SettingDialog
        deviceId={deviceId}
        setting={editing}
        canSend={canControl && available.has("SET_SETTING")}
        canRequest={canControl && available.has("REQUEST_SETTING")}
        canRecord={canRecord}
        onClose={() => setEditing(null)}
      />
    </div>
  );
}

/** Set (a downlink through the command pipeline) or record (a person's knowledge) one value. */
function SettingDialog({
  deviceId,
  setting,
  canSend,
  canRequest,
  canRecord,
  onClose,
}: {
  deviceId: string;
  setting: DeviceSetting | null;
  canSend: boolean;
  canRequest: boolean;
  canRecord: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [on, setOn] = useState(false);
  const value =
    setting?.type === "bool"
      ? on
      : setting?.type === "string" || setting?.type === "byte_array"
        ? text
        : Number(text);
  const valid =
    setting !== null &&
    (setting.type === "bool" ||
      (text.trim() !== "" &&
        (setting.type === "string" ||
          setting.type === "byte_array" ||
          Number.isFinite(Number(text)))));
  const send = useMutationToast({
    mutationFn: () =>
      api.post<CommandItem>(`/api/v1/devices/${deviceId}/commands`, {
        body: {
          action_key: "SET_SETTING",
          parameters: { setting: setting?.key, value },
          confirmed: true,
        },
      }),
    success: t("Sent; the value shows as sent until the collar confirms it"),
    invalidate: [
      queryKeys.deviceSettings(deviceId),
      queryKeys.deviceCommands(deviceId),
    ],
    onSuccess: onClose,
  });
  const ask = useMutationToast({
    mutationFn: () =>
      api.post<CommandItem>(`/api/v1/devices/${deviceId}/commands`, {
        body: {
          action_key: "REQUEST_SETTING",
          parameters: { setting: setting?.key },
          confirmed: true,
        },
      }),
    success: t("Asked; the value shows here when the collar answers"),
    invalidate: [queryKeys.deviceCommands(deviceId)],
    onSuccess: onClose,
  });
  const record = useMutationToast({
    mutationFn: () =>
      api.put<DeviceSetting>(
        `/api/v1/devices/${deviceId}/settings/${setting?.key}`,
        { body: { value } },
      ),
    success: t("Recorded as known"),
    invalidate: [queryKeys.deviceSettings(deviceId)],
    onSuccess: onClose,
  });
  return (
    <Dialog open={setting !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-mono">{setting?.key}</DialogTitle>
          <DialogDescription>
            {setting?.description ?? t("A setting of the collar's firmware.")}{" "}
            {setting &&
              setting.type !== "bool" &&
              setting.min !== null &&
              setting.max !== null &&
              t("Range {{min}} to {{max}}{{unit}}.", {
                min: String(setting.min),
                max: String(setting.max),
                unit: setting.unit ? ` ${setting.unit}` : "",
              })}
          </DialogDescription>
        </DialogHeader>
        {setting && (
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {setting.value !== null
                ? t("Known: {{value}} ({{source}})", {
                    value: showValue(setting, setting.value),
                    source: t(SOURCE_LABELS[setting.source ?? ""] ?? ""),
                  })
                : t("Not known yet; the default is {{value}}.", {
                    value: showValue(setting, setting.default) || "–",
                  })}
            </p>
            {setting.type === "bool" ? (
              <label className="flex items-center gap-2">
                <Switch checked={on} onCheckedChange={setOn} />
                {on ? t("on") : t("off")}
              </label>
            ) : (
              <Field
                label={
                  setting.unit
                    ? t("New value ({{unit}})", { unit: setting.unit })
                    : t("New value")
                }
                htmlFor="setting-value"
              >
                <Input
                  id="setting-value"
                  type={
                    setting.type === "string" || setting.type === "byte_array"
                      ? "text"
                      : "number"
                  }
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    setting.type === "byte_array" ? t("hex bytes") : ""
                  }
                />
              </Field>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("Cancel")}
          </Button>
          {canRequest && (
            <Button
              variant="outline"
              disabled={ask.isPending}
              onClick={() => ask.mutate()}
              title={t(
                "A few bytes each way: the way to read one setting over LoRaWAN or satellite",
              )}
            >
              <RefreshCw className="size-4" /> {t("Ask the collar")}
            </Button>
          )}
          {canRecord && (
            <Button
              variant="outline"
              disabled={!valid || record.isPending}
              onClick={() => record.mutate()}
            >
              <Check className="size-4" /> {t("Record as known")}
            </Button>
          )}
          {canSend && (
            <Button
              disabled={!valid || send.isPending}
              onClick={() => send.mutate()}
            >
              {t("Send to the collar")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
