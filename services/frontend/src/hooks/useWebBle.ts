/**
 * The WebBLE session of a device for the page: connection state, the protocol session, and the
 * sync that hands every received frame to the backend as deliveries (architecture 25.4).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { DeviceLogFile, RouteOption } from "@/api/types";
import { hex, type OpenCollarSession } from "@/lib/opencollar-ble";
import { useWebBleStore, webBleSession } from "@/stores/webble";

export function useWebBle(deviceId: string) {
  const client = useQueryClient();
  const connection = useWebBleStore((s) => s.connections[deviceId] ?? null);
  const store = useWebBleStore();

  /** Frames received since the last sync become a log file of channel webble. */
  const sync = useCallback(async (label: string, session?: OpenCollarSession): Promise<DeviceLogFile | null> => {
    const active = session ?? webBleSession(deviceId);
    if (!active) return null;
    const frames = active.takeReceived();
    if (frames.length === 0) return null;
    try {
      const file = await api.post<DeviceLogFile>(`/api/v1/devices/${deviceId}/log-files/ble-sync`, {
        body: { frames: frames.map((f) => hex(f.raw)), ble_synced_at: frames[frames.length - 1].at.toISOString(), label, attributes: { device_name: active.name, user_agent: navigator.userAgent } },
      });
      await client.invalidateQueries({ queryKey: queryKeys.logFiles(deviceId) });
      toast.success(`${frames.length} frames synced as ${file.original_filename}`);
      return file;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (message.includes("synced before")) toast.info("These frames were synced before.");
      else toast.error(`Sync failed: ${message}`);
      return null;
    }
  }, [client, deviceId]);

  const connect = useCallback(async (namePrefix?: string): Promise<OpenCollarSession> => {
    const session = await store.connect(deviceId, namePrefix);
    try {
      await api.post<RouteOption>(`/api/v1/devices/${deviceId}/routes/webble`);
      await client.invalidateQueries({ queryKey: queryKeys.deviceRoutes(deviceId) });
    } catch (error) {
      toast.error(`Connected, but the browser route could not be registered: ${error instanceof Error ? error.message : String(error)}`);
    }
    return session;
  }, [client, deviceId, store]);

  const disconnect = useCallback(async () => {
    await sync("session");
    await store.disconnect(deviceId);
    await client.invalidateQueries({ queryKey: queryKeys.deviceRoutes(deviceId) });
  }, [client, deviceId, store, sync]);

  return { connection, session: webBleSession(deviceId), connect, disconnect, sync, setStatus: store.setStatus, setFlash: store.setFlash };
}
