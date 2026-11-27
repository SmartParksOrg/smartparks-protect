import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Download, FileJson, FileUp, GitCompare, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { api, downloadFile } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  DeviceSetting,
  SettingsFile,
  SettingsFileList,
  SettingsFileStored,
} from "@/api/types";
import { Ago } from "@/components/common/Ago";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { t } from "@/lib/i18nMark";
import { compareFile, exportedAt } from "@/lib/settingsFile";

const SOURCE_LABELS: Record<string, string> = {
  upload: t("uploaded"),
  ble: t("read over Bluetooth"),
};

function show(type: string, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (type === "bool") return value ? "on" : "off";
  return String(value);
}

/**
 * The settings files of a device (decisions D426 to D429): the files the Smart Parks
 * ble-settings-app exports, uploaded here, and the snapshots Protect makes when the device's
 * settings are read over Bluetooth and something changed. Every file downloads in the app's
 * own format, so it imports there; "Export current" writes what Protect knows now.
 */
export function SettingsFilesCard({
  deviceId,
  settings,
}: {
  deviceId: string;
  settings: DeviceSetting[];
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const files = useQuery({
    queryKey: queryKeys.settingsFiles(deviceId),
    queryFn: () =>
      api.get<SettingsFileList>(`/api/v1/devices/${deviceId}/settings-files`),
  });
  const mayControl = files.data?.can_download_credentials ?? false;
  const [withCredentials, setWithCredentials] = useState(true);
  const credentials = mayControl && withCredentials;
  const [comparing, setComparing] = useState<SettingsFile | null>(null);
  const [deleting, setDeleting] = useState<SettingsFile | null>(null);
  const base = `/api/v1/devices/${deviceId}/settings-files`;

  const upload = useMutationToast({
    mutationFn: async (file: File) => {
      let document: unknown;
      try {
        document = JSON.parse(await file.text());
      } catch {
        throw new Error(
          t("{{name}} is no JSON file", { name: file.name }),
        );
      }
      return api.post<SettingsFileStored>(base, {
        body: {
          filename: file.name,
          document,
          exported_at: exportedAt(file.name)?.toISOString() ?? null,
        },
      });
    },
    invalidate: [
      queryKeys.settingsFiles(deviceId),
      queryKeys.deviceSettings(deviceId),
    ],
    onSuccess: (stored) => {
      if (!stored.created)
        toast.info(t("The device holds this file already."));
      else
        toast.success(
          t("{{name}} kept; {{count}} settings became known from it", {
            name: stored.file.filename,
            count: stored.recorded,
          }),
        );
      const skipped = [...stored.unknown, ...Object.keys(stored.invalid)];
      if (skipped.length > 0)
        toast.warning(
          t("Not read from the file: {{names}}", {
            names: skipped.join(", "),
          }),
        );
    },
  });
  const remove = useMutationToast({
    mutationFn: (file: SettingsFile) =>
      api.delete<void>(`${base}/${file.id}`),
    invalidate: [queryKeys.settingsFiles(deviceId)],
    success: t("Settings file deleted"),
    onSuccess: () => setDeleting(null),
  });

  async function download(path: string, name: string) {
    try {
      await downloadFile(path, name, { credentials });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }

  const known = settings.some((s) => s.value !== null && s.value !== undefined);
  return (
    <>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
          <CardTitle className="flex items-center gap-2">
            <FileJson className="size-4" /> {t("Settings files")}
            {files.data && files.data.total > 0 && (
              <span className="text-sm font-normal text-muted-foreground">
                {files.data.total}
              </span>
            )}
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {mayControl && (
              <label className="flex items-center gap-2 text-xs">
                <Switch
                  checked={withCredentials}
                  onCheckedChange={setWithCredentials}
                />
                {t("Downloads with device credentials")}
              </label>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={!known}
              onClick={() =>
                void download(`${base}/current/download`, "settings.json")
              }
            >
              <Download className="size-4" /> {t("Export current")}
            </Button>
            {mayControl && (
              <>
                <input
                  ref={input}
                  type="file"
                  accept=".json,application/json"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload.mutate(file);
                    e.target.value = "";
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={upload.isPending}
                  onClick={() => input.current?.click()}
                >
                  <FileUp className="size-4" />{" "}
                  {upload.isPending ? t("Uploading…") : t("Upload")}
                </Button>
              </>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">
            {t(
              "Files in the format of the Smart Parks settings app: upload one you exported there, or download one here and import it there. Protect adds a file by itself when it reads the device's settings over Bluetooth and something changed.",
            )}
          </p>
          {files.isError && (
            <Callout kind="error">{files.error.message}</Callout>
          )}
          {files.data && files.data.items.length === 0 && (
            <p className="text-muted-foreground">{t("No settings files yet.")}</p>
          )}
          {files.data && files.data.items.length > 0 && (
            <div className="rounded-md border">
              {files.data.items.map((file) => (
                <div
                  key={file.id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-2 first:border-t-0"
                >
                  <div className="min-w-0 flex-1 basis-56">
                    <div className="font-medium break-all">{file.filename}</div>
                    <div className="text-xs text-muted-foreground">
                      {t(SOURCE_LABELS[file.source] ?? file.source)}
                      {" · "}
                      <Ago value={file.observed_at ?? file.created_at} />
                      {" · "}
                      {t("{{count}} settings", { count: file.settings_count })}
                      {file.firmware_version &&
                        ` · ${t("firmware {{v}}", { v: file.firmware_version })}`}
                      {file.has_credentials &&
                        ` · ${t("with credentials")}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setComparing(file)}
                    >
                      <GitCompare className="size-4" /> {t("Compare")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("Download {{name}}", {
                        name: file.filename,
                      })}
                      onClick={() =>
                        void download(
                          `${base}/${file.id}/download`,
                          file.filename,
                        )
                      }
                    >
                      <Download className="size-4" />
                    </Button>
                    {mayControl && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("Delete {{name}}", {
                          name: file.filename,
                        })}
                        onClick={() => setDeleting(file)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {files.data && files.data.total > files.data.items.length && (
            <p className="text-xs text-muted-foreground">
              {t("The newest {{shown}} of {{total}} files.", {
                shown: files.data.items.length,
                total: files.data.total,
              })}
            </p>
          )}
        </CardContent>
      </Card>
      {comparing && (
        <CompareDialog
          deviceId={deviceId}
          file={comparing}
          settings={settings}
          onClose={() => setComparing(null)}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("Delete {{name}}?", { name: deleting?.filename ?? "" })}
        description={t(
          "The file is removed from this device. The settings Protect knows stay as they are.",
        )}
        confirmLabel={t("Delete")}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  );
}

/** A stored file beside what Protect knows of the device now: only what differs. */
function CompareDialog({
  deviceId,
  file,
  settings,
  onClose,
}: {
  deviceId: string;
  file: SettingsFile;
  settings: DeviceSetting[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  // without the credentials: they are not compared, so a look at a file leaves no trace of
  // a key having been read
  const document = useQuery({
    queryKey: [...queryKeys.settingsFiles(deviceId), file.id, "document"],
    queryFn: () =>
      api.get<Record<string, unknown>>(
        `/api/v1/devices/${deviceId}/settings-files/${file.id}/download`,
      ),
  });
  const comparison = document.data
    ? compareFile(document.data, settings)
    : null;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-8 break-all">{file.filename}</DialogTitle>
          <DialogDescription>
            {t(
              "The file beside what Protect knows of the device now. Device credentials are not compared.",
            )}
          </DialogDescription>
        </DialogHeader>
        {document.isError && (
          <Callout kind="error">{document.error.message}</Callout>
        )}
        {comparison && (
          <div className="space-y-2 text-sm">
            <p>
              {comparison.different.length === 0
                ? t("All {{count}} settings of the file are what Protect knows.", {
                    count: comparison.same,
                  })
                : t("{{different}} settings differ, {{same}} are the same.", {
                    different: comparison.different.length,
                    same: comparison.same,
                  })}
            </p>
            {comparison.different.length > 0 && (
              <div className="rounded-md border">
                <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] gap-x-3 border-b bg-muted/40 px-3 py-1.5 text-xs font-medium">
                  <span>{t("Setting")}</span>
                  <span>{t("In the file")}</span>
                  <span>{t("Known in Protect")}</span>
                </div>
                {comparison.different.map((row) => (
                  <div
                    key={row.key}
                    className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] gap-x-3 border-t px-3 py-1.5 first:border-t-0"
                  >
                    <span className="font-mono text-xs break-all">
                      {row.key}
                    </span>
                    <span className="break-all tabular-nums">
                      {row.file === undefined
                        ? t("does not fit")
                        : show(row.type, row.file)}
                    </span>
                    <span className="break-all tabular-nums text-muted-foreground">
                      {row.known === null
                        ? t("unknown")
                        : show(row.type, row.known)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {comparison.unknown.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {t(
                  "Not in the catalogue of the device's firmware: {{names}}",
                  { names: comparison.unknown.join(", ") },
                )}
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
