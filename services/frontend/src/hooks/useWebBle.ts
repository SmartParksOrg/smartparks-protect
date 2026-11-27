/**
 * The WebBLE session of a device for the page: connection state, the protocol session, and the
 * sync that hands every received frame to the backend as deliveries (architecture 25.4).
 */
import { t } from "@/lib/i18nMark";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  DeviceLogFile,
  RouteOption,
  SettingsSnapshotStored,
} from "@/api/types";
import {
  hex,
  type OpenCollarSession,
  type SettingsRead,
} from "@/lib/opencollar-ble";
import { useWebBleStore, webBleSession } from "@/stores/webble";

/** A settings read as the snapshot endpoint takes it; also used where the device was made
 * a moment ago and has no session in the store (the Add device form). */
export async function keepSettingsRead(
  deviceId: string,
  read: SettingsRead,
): Promise<SettingsSnapshotStored | null> {
  if (read.values.size === 0) return null;
  return api.post<SettingsSnapshotStored>(
    `/api/v1/devices/${deviceId}/settings-files/snapshot`,
    {
      body: {
        values: [...read.values].map(([id, value]) => ({
          id,
          hex: hex(value),
        })),
        firmware: read.firmware,
        read_at: read.at.toISOString(),
        complete: read.complete,
      },
    },
  );
}

export function useWebBle(deviceId: string) {
  const client = useQueryClient();
  const connection = useWebBleStore((s) => s.connections[deviceId] ?? null);
  const store = useWebBleStore();

  /** Frames received since the last sync become a log file of channel webble. */
  const sync = useCallback(
    async (
      label: string,
      session?: OpenCollarSession,
    ): Promise<DeviceLogFile | null> => {
      const active = session ?? webBleSession(deviceId);
      if (!active) return null;
      const frames = active.takeReceived();
      if (frames.length === 0) return null;
      try {
        const file = await api.post<DeviceLogFile>(
          `/api/v1/devices/${deviceId}/log-files/ble-sync`,
          {
            body: {
              frames: frames.map((f) => hex(f.raw)),
              ble_synced_at: frames[frames.length - 1].at.toISOString(),
              label,
              attributes: {
                device_name: active.name,
                user_agent: navigator.userAgent,
              },
            },
          },
        );
        await client.invalidateQueries({
          queryKey: queryKeys.logFiles(deviceId),
        });
        toast.success(
          `${frames.length} frames synced as ${file.original_filename}`,
        );
        return file;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (message.includes("synced before"))
          toast.info(t("These frames were synced before."));
        else toast.error(`Sync failed: ${message}`);
        return null;
      }
    },
    [client, deviceId],
  );

  /** Read every setting and hand it to Protect (decisions D427 and D428): the frames as a
   * sync like any other, the values as known at once, and a whole read as a snapshot in the
   * device's settings files when it differs from the newest one. */
  const readSettings = useCallback(
    async (session?: OpenCollarSession): Promise<SettingsRead | null> => {
      const active = session ?? webBleSession(deviceId);
      if (!active) return null;
      const read = await active.readSettings();
      await sync("settings", active);
      await keepSettingsRead(deviceId, read);
      await Promise.all([
        client.invalidateQueries({
          queryKey: queryKeys.deviceSettings(deviceId),
        }),
        client.invalidateQueries({
          queryKey: queryKeys.settingsFiles(deviceId),
        }),
      ]);
      return read;
    },
    [client, deviceId, sync],
  );

  const connect = useCallback(
    async (namePrefix?: string): Promise<OpenCollarSession> => {
      const session = await store.connect(deviceId, namePrefix);
      try {
        await api.post<RouteOption>(
          `/api/v1/devices/${deviceId}/routes/webble`,
        );
        await client.invalidateQueries({
          queryKey: queryKeys.deviceRoutes(deviceId),
        });
      } catch (error) {
        toast.error(
          `Connected, but the browser route could not be registered: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      return session;
    },
    [client, deviceId, store],
  );

  const disconnect = useCallback(async () => {
    await sync("session");
    await store.disconnect(deviceId);
    await client.invalidateQueries({
      queryKey: queryKeys.deviceRoutes(deviceId),
    });
  }, [client, deviceId, store, sync]);

  return {
    connection,
    session: webBleSession(deviceId),
    connect,
    disconnect,
    sync,
    readSettings,
    setStatus: store.setStatus,
    setFlash: store.setFlash,
  };
}
