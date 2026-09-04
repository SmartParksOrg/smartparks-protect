/**
 * Web Bluetooth sessions per device (architecture 25.4). The protocol session object is not
 * serialisable, so it lives in a module map; the store only carries what components render
 * (connected, name, last status). One session per device, in this tab.
 */
import { create } from "zustand";

import { connectWebBluetooth, OpenCollarSession, type StatusMessage } from "@/lib/opencollar-ble";

const sessions = new Map<string, OpenCollarSession>();

export interface WebBleConnection {
  name: string;
  since: string;
  status: StatusMessage | null;
  flash: { usedPercent: number; messages: number } | null;
}

interface WebBleState {
  connections: Record<string, WebBleConnection>;
  connect: (deviceId: string, namePrefix?: string) => Promise<OpenCollarSession>;
  disconnect: (deviceId: string) => Promise<void>;
  setStatus: (deviceId: string, status: StatusMessage | null) => void;
  setFlash: (deviceId: string, flash: WebBleConnection["flash"]) => void;
}

export const useWebBleStore = create<WebBleState>()((set, get) => ({
  connections: {},
  async connect(deviceId, namePrefix) {
    const existing = sessions.get(deviceId);
    if (existing) return existing;
    const transport = await connectWebBluetooth(namePrefix);
    const session = new OpenCollarSession(transport);
    sessions.set(deviceId, session);
    transport.onDisconnect?.(() => {
      sessions.delete(deviceId);
      set((state) => { const next = { ...state.connections }; delete next[deviceId]; return { connections: next }; });
    });
    set((state) => ({ connections: { ...state.connections, [deviceId]: { name: transport.name, since: new Date().toISOString(), status: null, flash: null } } }));
    return session;
  },
  async disconnect(deviceId) {
    const session = sessions.get(deviceId);
    sessions.delete(deviceId);
    set((state) => { const next = { ...state.connections }; delete next[deviceId]; return { connections: next }; });
    await session?.disconnect();
  },
  setStatus(deviceId, status) {
    const current = get().connections[deviceId];
    if (current) set((state) => ({ connections: { ...state.connections, [deviceId]: { ...current, status } } }));
  },
  setFlash(deviceId, flash) {
    const current = get().connections[deviceId];
    if (current) set((state) => ({ connections: { ...state.connections, [deviceId]: { ...current, flash } } }));
  },
}));

export function webBleSession(deviceId: string): OpenCollarSession | undefined {
  return sessions.get(deviceId);
}
