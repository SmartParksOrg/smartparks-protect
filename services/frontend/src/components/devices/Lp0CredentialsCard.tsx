import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Copy, Eye, EyeOff, KeyRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Lp0Credentials } from "@/api/types";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const ADDRESS = /^[0-9A-Fa-f]{8}$/;
const KEY = /^[0-9A-Fa-f]{32}$/;
const clean = (text: string) => text.replace(/[\s:_-]/g, "");

/**
 * The tracker's LP0 address and keys (phase 42, decision D320): provisioned per device like its
 * DevEUI, they are what lets Protect verify and decrypt the frames an offload station stored
 * for it. Typed in, or taken from what the device reported in its own settings readback. The
 * keys are shown and changeable to whoever may set them (Tim, 2026-10-15: the credentials are
 * important and must be visible and changeable when needed): each key has its line, named as
 * the LoRaWAN variable, its value masked until the eye beside it is pressed (Tim, 2026-10-18),
 * so a screen over a shoulder does not carry them; a viewer sees only that they are set.
 */
export function Lp0CredentialsCard({
  deviceId,
  canEdit,
}: {
  deviceId: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [address, setAddress] = useState("");
  const [appKey, setAppKey] = useState("");
  const [nwkKey, setNwkKey] = useState("");
  const read = useQuery({
    queryKey: queryKeys.lp0Credentials(deviceId),
    queryFn: () =>
      api.get<Lp0Credentials>(`/api/v1/devices/${deviceId}/lp0-credentials`),
  });
  const invalidate = [
    queryKeys.lp0Credentials(deviceId),
    queryKeys.logFiles(deviceId),
    queryKeys.device(deviceId),
  ];
  const save = useMutationToast({
    mutationFn: (body: {
      dev_addr?: string;
      app_s_key?: string;
      nwk_s_key?: string;
      from_device?: boolean;
    }) =>
      api.put<Lp0Credentials & { queued: number }>(
        `/api/v1/devices/${deviceId}/lp0-credentials`,
        { body },
      ),
    invalidate,
    success: (r) =>
      !r.keys_set
        ? t("LP0 address saved; {{count}} frames wait for the keys", {
            count: r.frames_waiting,
          })
        : r.queued > 0
          ? t(
              "LP0 keys saved; {{count}} waiting frames handed to the decoder",
              {
                count: r.queued,
              },
            )
          : t("LP0 keys saved"),
    onSuccess: () => setEditing(false),
  });
  const clear = useMutationToast({
    mutationFn: () =>
      api.delete<void>(`/api/v1/devices/${deviceId}/lp0-credentials`),
    invalidate,
    success: t("LP0 keys cleared"),
    onSuccess: () => setClearing(false),
  });
  const c = read.data;
  const readback = c?.readback;
  // the address alone claims the frames a card holds for it (decision D338); both keys or
  // neither
  const keysGiven = clean(appKey) !== "" || clean(nwkKey) !== "";
  const valid =
    ADDRESS.test(clean(address)) &&
    (!keysGiven || (KEY.test(clean(appKey)) && KEY.test(clean(nwkKey))));
  const readbackComplete =
    Boolean(readback?.dev_addr) &&
    Boolean(readback?.app_key_known) &&
    Boolean(readback?.network_key_known);
  const copy = (value: string, label: string) => {
    navigator.clipboard
      .writeText(value)
      .then(() => toast.success(t("{{label}} copied", { label })))
      .catch(() => toast.error(t("Could not copy")));
  };
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4" /> {t("LP0 offload")}
        </CardTitle>
        {canEdit && c && !editing && (
          <span className="flex gap-1">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setAddress(c.dev_addr ?? readback?.dev_addr ?? "");
                setAppKey(c.app_s_key ?? "");
                setNwkKey(c.nwk_s_key ?? "");
                setEditing(true);
              }}
            >
              {c.keys_set
                ? t("Change")
                : c.dev_addr
                  ? t("Set the keys")
                  : t("Set address and keys")}
            </Button>
            {c.keys_set && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setClearing(true)}
              >
                {t("Clear")}
              </Button>
            )}
          </span>
        )}
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p className="text-xs text-muted-foreground">
          {t(
            "The address and the two session keys the device uses to offload its flash log to an offload station. Protect decrypts the frames on a station's card with them; without them a card holds nothing readable of this device.",
          )}
        </p>
        {c && !editing && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">{t("LP0 address")}</dt>
            <dd className={c.dev_addr ? "font-mono" : "text-muted-foreground"}>
              {c.dev_addr ?? t("not set")}
            </dd>
            <dt className="text-muted-foreground">{t("Keys")}</dt>
            <dd>
              {c.keys_set
                ? c.source === "device"
                  ? t("set from the device's own readback, {{time}}", {
                      time: formatTime(c.set_at),
                    })
                  : t("set by a person, {{time}}", {
                      time: formatTime(c.set_at),
                    })
                : t("not set")}
            </dd>
            {c.keys_set && (
              <>
                <KeyRow
                  label="AppSKey"
                  title={t("Application session key")}
                  value={c.app_s_key ?? null}
                  onCopy={() => copy(c.app_s_key ?? "", "AppSKey")}
                />
                <KeyRow
                  label="NwkSKey"
                  title={t("Network session key")}
                  value={c.nwk_s_key ?? null}
                  onCopy={() => copy(c.nwk_s_key ?? "", "NwkSKey")}
                />
              </>
            )}
            {c.frames_waiting > 0 && (
              <>
                <dt className="text-muted-foreground">{t("Waiting")}</dt>
                <dd>
                  {t(
                    "{{count}} frames stored for this address wait for the keys",
                    {
                      count: c.frames_waiting,
                    },
                  )}
                </dd>
              </>
            )}
            {readback?.dev_addr && (
              <>
                <dt className="text-muted-foreground">
                  {t("Reported by the device")}
                </dt>
                <dd>
                  <span className="font-mono">{readback.dev_addr}</span>
                  {readbackComplete
                    ? t(", both keys read")
                    : t(", keys not read")}
                  {canEdit && readbackComplete && (
                    <Button
                      size="sm"
                      variant="link"
                      className="h-auto px-2 py-0"
                      disabled={save.isPending}
                      onClick={() => save.mutate({ from_device: true })}
                    >
                      {t("Use the device's reported values")}
                    </Button>
                  )}
                </dd>
              </>
            )}
          </dl>
        )}
        {editing && (
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (valid)
                save.mutate({
                  dev_addr: clean(address),
                  ...(keysGiven
                    ? { app_s_key: clean(appKey), nwk_s_key: clean(nwkKey) }
                    : {}),
                });
            }}
          >
            <label className="block text-xs text-muted-foreground">
              {t("LP0 address (8 hex digits)")}
              <Input
                className="mt-1 font-mono"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="26010203"
                autoComplete="off"
              />
            </label>
            <p className="text-xs text-muted-foreground">
              {t(
                "The address alone is enough to claim the frames a card holds for it; the keys may follow, and the frames wait until then.",
              )}
            </p>
            <label className="block text-xs text-muted-foreground">
              {t("AppSKey, the application session key (32 hex digits)")}
              <Input
                className="mt-1 font-mono"
                value={appKey}
                onChange={(e) => setAppKey(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <label className="block text-xs text-muted-foreground">
              {t("NwkSKey, the network session key (32 hex digits)")}
              <Input
                className="mt-1 font-mono"
                value={nwkKey}
                onChange={(e) => setNwkKey(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <div className="flex gap-2">
              <Button
                type="submit"
                size="sm"
                disabled={!valid || save.isPending}
              >
                {t("Save")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
              >
                {t("Cancel")}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("Clear the LP0 keys?")}
        description={t(
          "Frames an offload station stored for this device can no longer be decrypted until the keys are set again; nothing already decoded is lost.",
        )}
        confirmLabel={t("Clear")}
        onConfirm={() => clear.mutate(undefined)}
        pending={clear.isPending}
      />
    </Card>
  );
}

/** One key's line: the variable's name, the value masked or shown, the eye and the copy button.
 * A viewer who may not change the keys sees that the key is set and nothing more. */
function KeyRow({
  label,
  title,
  value,
  onCopy,
}: {
  label: string;
  title: string;
  value: string | null;
  onCopy: () => void;
}) {
  const { t } = useTranslation();
  const [shown, setShown] = useState(false);
  return (
    <>
      <dt className="text-muted-foreground" title={title}>
        {label}
      </dt>
      <dd className="flex min-w-0 items-center gap-1">
        {value ? (
          <>
            <span className="min-w-0 break-all font-mono text-xs">
              {shown ? value : "•".repeat(32)}
            </span>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 shrink-0 px-1"
              aria-pressed={shown}
              aria-label={
                shown
                  ? t("Hide {{label}}", { label })
                  : t("Show {{label}}", { label })
              }
              onClick={() => setShown((v) => !v)}
            >
              {shown ? (
                <EyeOff className="size-3.5" />
              ) : (
                <Eye className="size-3.5" />
              )}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 shrink-0 px-1"
              aria-label={t("Copy {{label}}", { label })}
              onClick={onCopy}
            >
              <Copy className="size-3.5" />
            </Button>
          </>
        ) : (
          <span className="text-muted-foreground">
            {t("set, shown to those who may change it")}
          </span>
        )}
      </dd>
    </>
  );
}
