import { useQuery } from "@tanstack/react-query";
import { Bluetooth, BluetoothOff, Download, Eraser, RefreshCw, Settings2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DriverCatalog } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useWebBle } from "@/hooks/useWebBle";
import { type Catalog, type CatalogSetting, decodeSettingValue, webBluetoothAvailable } from "@/lib/opencollar-ble";
import { formatAgo } from "@/lib/format";

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The settings table of the connected device: current values read over BLE, editable per row
 * (research 4.4). Keys and binary blobs are shown as hex. */
function SettingsEditor({ catalog, values, onWrite, canWrite }: { catalog: Catalog; values: Map<number, Uint8Array>; onWrite: (setting: CatalogSetting, value: unknown) => Promise<void>; canWrite: boolean }) {
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [filter, setFilter] = useState("");
  const rows = catalog.settings.filter((s) => !filter || s.name.includes(filter.toLowerCase()));
  return (
    <div className="space-y-2">
      <Input placeholder="Filter settings" value={filter} onChange={(e) => setFilter(e.target.value)} className="h-8 max-w-xs" />
      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted"><tr><th className="p-1 text-left">Setting</th><th className="p-1 text-left">Type</th><th className="p-1 text-left">Device</th>{canWrite && <th className="p-1 text-left">New value</th>}</tr></thead>
          <tbody>
            {rows.map((s) => {
              const raw = values.get(s.id);
              const current = raw ? decodeSettingValue(s.type, raw) : undefined;
              const draft = drafts[s.id];
              const secret = s.type === "byte_array" && /key|pin/.test(s.name);
              return (
                <tr key={s.id} className="border-t">
                  <td className="p-1 font-mono">{s.name} <span className="text-muted-foreground">0x{s.id.toString(16).padStart(2, "0")}</span></td>
                  <td className="p-1 text-muted-foreground">{s.type}{s.min != null && s.max != null && s.type !== "bool" ? ` ${String(s.min)} to ${String(s.max)}` : ""}</td>
                  <td className="p-1 font-mono">{raw === undefined ? <span className="text-muted-foreground">not reported</span> : secret ? "••••" : String(current)}</td>
                  {canWrite && (
                    <td className="p-1">
                      <span className="flex items-center gap-1">
                        {s.type === "bool" ? (
                          <Switch checked={draft === undefined ? current === true : draft === "true"} onCheckedChange={(v) => setDrafts({ ...drafts, [s.id]: String(v) })} />
                        ) : (
                          <Input className="h-7 w-40 font-mono text-xs" value={draft ?? ""} placeholder={raw === undefined ? String(s.default ?? "") : ""} onChange={(e) => setDrafts({ ...drafts, [s.id]: e.target.value })} />
                        )}
                        <Button size="sm" variant="outline" className="h-7" disabled={draft === undefined} onClick={async () => { await onWrite(s, s.type === "bool" ? draft === "true" : draft); setDrafts((d) => { const next = { ...d }; delete next[s.id]; return next; }); }}>write</Button>
                      </span>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Web Bluetooth to a nearby OpenCollar (architecture 25.4, decision D76): status, settings,
 * flash logs, all synced to the backend as deliveries. Commands go through Control with the
 * WebBLE route (decision D79). */
export function WebBleCard({ deviceId, deviceName, driverKey, canWrite }: { deviceId: string; deviceName: string; driverKey: string | undefined; canWrite: boolean }) {
  const ble = useWebBle(deviceId);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ frames: number; bytes: number } | null>(null);
  const [settings, setSettings] = useState<Map<number, Uint8Array> | null>(null);
  const [erasing, setErasing] = useState(false);
  const catalog = useQuery({ queryKey: queryKeys.driverCatalog(deviceId), queryFn: () => api.get<DriverCatalog>(`/api/v1/devices/${deviceId}/driver-catalog`), enabled: Boolean(ble.connection) });
  if (driverKey !== "opencollar") return null;
  const available = webBluetoothAvailable();
  const connection = ble.connection;

  async function run<T>(label: string, task: () => Promise<T>): Promise<T | undefined> {
    setBusy(label);
    try {
      return await task();
    } catch (error) {
      toast.error(`${label} failed: ${describe(error)}`);
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  async function refreshStatus() {
    const session = ble.session;
    if (!session) return;
    await run("Status", async () => {
      ble.setStatus(deviceId, await session.requestStatus());
      ble.setFlash(deviceId, await session.requestFlashStatus());
    });
  }

  async function connect() {
    await run("Connect", async () => {
      const session = await ble.connect(deviceName.startsWith("SP") ? deviceName.slice(0, 4) : undefined);
      try {
        ble.setStatus(deviceId, await session.requestStatus());
        ble.setFlash(deviceId, await session.requestFlashStatus());
      } catch (error) {
        toast.info(`Connected; no status yet (${describe(error)}). The device may be PIN locked.`);
      }
      await ble.sync("connect", session);
    });
  }

  async function downloadLogs() {
    const session = ble.session;
    if (!session) return;
    await run("Log download", async () => {
      setProgress({ frames: 0, bytes: 0 });
      const result = await session.downloadLogs(0, (frames, bytes) => setProgress({ frames, bytes }));
      setProgress(null);
      if (result.frames.length === 0) toast.info(result.confirmed ? "The device holds no logs." : "No frames arrived; the device did not answer.");
      else toast.success(`${result.frames.length} log frames read${result.confirmed ? "" : " (no confirmation, the link went quiet)"}`);
      await ble.sync("flash-log", session);
      ble.setFlash(deviceId, await session.requestFlashStatus());
    });
  }

  async function readSettings() {
    const session = ble.session;
    if (!session) return;
    await run("Settings", async () => {
      setSettings(await session.requestSettings());
      await ble.sync("settings", session);
    });
  }

  async function writeSetting(setting: CatalogSetting, value: unknown) {
    const session = ble.session;
    if (!session) return;
    await run(`Write ${setting.name}`, async () => {
      const confirmed = await session.writeSetting(setting, value);
      if (confirmed === false) toast.error(`The device rejected ${setting.name}`);
      else toast.success(`${setting.name} written${confirmed === null ? " (no confirmation from the device)" : ""}`);
      setSettings(await session.requestSettings());
      await ble.sync("settings", session);
    });
  }

  async function eraseLogs() {
    const session = ble.session;
    if (!session) return;
    setErasing(false);
    await run("Erase logs", async () => {
      const ok = await session.eraseLogs();
      toast[ok ? "success" : "error"](ok ? "Device flash erased" : "The device reported a failure");
      ble.setFlash(deviceId, await session.requestFlashStatus());
      await ble.sync("erase", session);
    });
  }

  const status = connection?.status;
  const errors = status ? Object.entries(status.errors).filter(([, on]) => on).map(([name]) => name) : [];
  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2"><Bluetooth className="size-4" /> Nearby over Bluetooth</CardTitle>
          {connection ? (
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run("Disconnect", ble.disconnect)}><BluetoothOff className="size-4" /> Disconnect</Button>
          ) : (
            <Button size="sm" disabled={!available || busy !== null || !canWrite} onClick={connect}><Bluetooth className="size-4" /> {busy === "Connect" ? "Connecting…" : "Connect"}</Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!available && <Callout kind="info">Web Bluetooth needs Chrome or Edge over HTTPS (or localhost). Safari and Firefox do not offer it.</Callout>}
          {available && !connection && <p className="text-muted-foreground">Connect the collar next to you to read its status and settings and to retrieve stored logs. Everything read is stored as a delivery on the WebBLE channel; commands are sent from Control with the WebBLE route.</p>}
          {available && !canWrite && <p className="text-xs text-muted-foreground">Connecting needs the device control permission in this project.</p>}
          {connection && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{connection.name}</span>
                <span className="text-xs text-muted-foreground">connected {formatAgo(connection.since)}</span>
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" disabled={busy !== null} onClick={refreshStatus}><RefreshCw className="size-4" /> status</Button>
                  <Button size="sm" variant="ghost" disabled={busy !== null} onClick={readSettings}><Settings2 className="size-4" /> settings</Button>
                  <Button size="sm" variant="ghost" disabled={busy !== null} onClick={downloadLogs}><Download className="size-4" /> logs</Button>
                  {canWrite && <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => setErasing(true)}><Eraser className="size-4" /> erase</Button>}
                </span>
              </div>
              {status && (
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                  <dt className="text-muted-foreground">Battery</dt><dd>{(status.batteryMv / 1000).toFixed(2)} V{status.chargingMv ? `, charging at ${(status.chargingMv / 1000).toFixed(1)} V` : ""}</dd>
                  <dt className="text-muted-foreground">Temperature</dt><dd>{status.temperatureC} °C</dd>
                  <dt className="text-muted-foreground">Firmware</dt><dd>{status.firmwareVersion} on hardware {status.hardwareVersion} (types {status.firmwareType}/{status.hardwareType})</dd>
                  <dt className="text-muted-foreground">Uptime</dt><dd>{status.uptimeDays} days{status.locked ? ", PIN locked" : ""}{status.joinError ? ", LoRaWAN join error" : ""}</dd>
                  <dt className="text-muted-foreground">Flash</dt><dd>{connection.flash ? `${connection.flash.messages} stored messages, ${connection.flash.usedPercent}% used` : "unknown"}</dd>
                  <dt className="text-muted-foreground">Errors</dt><dd className={errors.length ? "text-destructive" : ""}>{errors.length ? errors.join(", ") : "none"}</dd>
                </dl>
              )}
              {progress && <div className="text-xs text-muted-foreground">Reading logs: {progress.frames} frames, {Math.round(progress.bytes / 1024)} kB…</div>}
              {settings && catalog.data && (catalog.data.catalog as unknown as Catalog).settings && <SettingsEditor catalog={catalog.data.catalog as unknown as Catalog} values={settings} onWrite={writeSetting} canWrite={canWrite} />}
              {settings && catalog.data && !(catalog.data.catalog as unknown as Catalog).settings && <p className="text-xs text-muted-foreground">The driver publishes no settings catalogue; {settings.size} settings were read.</p>}
            </>
          )}
        </CardContent>
      </Card>
      <ConfirmDialog open={erasing} onOpenChange={setErasing} title="Erase the device's flash log?" description="Every stored record on the device is deleted. Sync the logs first; records already received are safe on the server." confirmLabel="Erase" pending={busy === "Erase logs"} onConfirm={eraseLogs} />
    </>
  );
}
