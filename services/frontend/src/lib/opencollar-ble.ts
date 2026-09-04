/**
 * OpenCollar Edge over Web Bluetooth (architecture 25.4, decision D76).
 *
 * Our own implementation of the protocol the public Smart Parks BLE settings app speaks,
 * written from `docs/devices/opencollar-protocol-research.md`: the Nordic UART service, frames
 * `[port][msg_id][len][data]` in both directions (research 1.1, 4.5), commands on port 32,
 * settings on port 3 as `[id][len][value]`, and flash logs streamed on port 29 after
 * `cmd_flash_get_all` (0xBB) or `cmd_flash_get_from_head` (0xBC), closed by a command
 * confirmation `F3 02 <cmd> <status>` on port 31 (research 3.20, 3.22).
 *
 * Every frame the device sends is kept so the page can hand it to the backend as a delivery
 * (channel `webble`); the raw log export is the same one-base64-frame-per-line format the
 * public app writes. Nothing here touches the network: the transport is injected so the
 * protocol can be tested without a device.
 */

export const NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
export const NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"; // write to the device
export const NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"; // notifications from the device
export const MANUFACTURER_ID = 0x0a61;

export const PORT = { settings: 3, status: 4, flashStatus: 14, timestamp: 18, flashLog: 29, values: 30, messages: 31, commands: 32 } as const;
export const CMD = {
  reset: 0xa1,
  sendStatus: 0xa4,
  sendPosition: 0xa5,
  sendAllSettings: 0xa7,
  sendSingleSetting: 0xa8,
  getFlashStatus: 0xb3,
  getUbloxFix: 0xb8,
  flashClear: 0xba,
  flashGetAll: 0xbb,
  flashGetFromHead: 0xbc,
  checkPin: 0xc2,
  sendTimestamp: 0xce,
} as const;
export const MSG = { cmdConfirm: 0xf3, status: 0xf4, flashStatus: 0x94, timestamp: 0x97, lastPosition: 0xfe } as const;

export type SettingType = "uint8" | "uint16" | "uint32" | "int8" | "int16" | "int32" | "bool" | "byte_array" | "string" | "float";

export interface CatalogSetting { id: number; name: string; length: number; type: SettingType; default: unknown; min: number | boolean | null; max: number | boolean | null }
export interface CatalogCommand { id: number; name: string; argument_length: number; description: string }
export interface Catalog { firmware?: string; settings: CatalogSetting[]; commands: CatalogCommand[]; values?: unknown[] }

export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function fromHex(text: string): Uint8Array {
  const clean = text.replace(/\s+/g, "");
  if (clean.length % 2 !== 0 || /[^0-9a-fA-F]/.test(clean)) throw new Error(`not hex: ${text}`);
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}

export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

/** `[port 32][cmd][len][argument]` (research 4.2). */
export function commandFrame(cmdId: number, argument: Uint8Array = new Uint8Array(0)): Uint8Array {
  return new Uint8Array([PORT.commands, cmdId, argument.length, ...argument]);
}

/** `[port 3][id][len][value]` (research 4.1). */
export function settingFrame(settingId: number, value: Uint8Array): Uint8Array {
  return new Uint8Array([PORT.settings, settingId, value.length, ...value]);
}

/** Little-endian encoding per the catalogue's `conversion` type (research 4.1). */
export function encodeSettingValue(type: SettingType, length: number, value: unknown): Uint8Array {
  const out = new Uint8Array(length);
  const view = new DataView(out.buffer);
  switch (type) {
    case "bool":
      out[0] = value === true || value === 1 || value === "true" || value === "1" ? 1 : 0;
      return out;
    case "uint8":
    case "uint16":
    case "uint32":
    case "int8":
    case "int16":
    case "int32": {
      const n = Number(value);
      if (!Number.isInteger(n)) throw new Error(`${type} needs an integer, got ${String(value)}`);
      const unsigned = type.startsWith("u");
      if (length === 1) {
        if (unsigned) view.setUint8(0, n);
        else view.setInt8(0, n);
      } else if (length === 2) {
        if (unsigned) view.setUint16(0, n, true);
        else view.setInt16(0, n, true);
      } else if (unsigned) view.setUint32(0, n >>> 0, true);
      else view.setInt32(0, n, true);
      return out;
    }
    case "float":
      view.setFloat32(0, Number(value), true);
      return out;
    case "byte_array": {
      const bytes = fromHex(String(value ?? ""));
      if (bytes.length !== length) throw new Error(`byte array needs ${length} bytes, got ${bytes.length}`);
      return bytes;
    }
    case "string": {
      const text = String(value ?? "");
      if (text.length > length) throw new Error(`string longer than ${length} characters`);
      for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i) & 0xff;
      return out;
    }
  }
}

export function decodeSettingValue(type: SettingType, bytes: Uint8Array): number | boolean | string {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  switch (type) {
    case "bool":
      return bytes[0] === 1;
    case "uint8":
      return view.getUint8(0);
    case "int8":
      return view.getInt8(0);
    case "uint16":
      return view.getUint16(0, true);
    case "int16":
      return view.getInt16(0, true);
    case "uint32":
      return view.getUint32(0, true);
    case "int32":
      return view.getInt32(0, true);
    case "float":
      return view.getFloat32(0, true);
    case "byte_array":
      return hex(bytes);
    case "string":
      return Array.from(bytes.filter((b) => b !== 0), (b) => String.fromCharCode(b)).join("");
  }
}

/** `[id][len][value]` repeated (ports 3 and 30). */
export function parseTlv(bytes: Uint8Array): Array<{ id: number; value: Uint8Array }> {
  const items: Array<{ id: number; value: Uint8Array }> = [];
  let i = 0;
  while (i + 2 <= bytes.length) {
    const id = bytes[i];
    const length = bytes[i + 1];
    items.push({ id, value: bytes.slice(i + 2, i + 2 + length) });
    i += 2 + length;
  }
  return items;
}

export interface StatusMessage {
  resetReason: { pin: boolean; watchdog: boolean; software: boolean; lockup: boolean };
  errors: Record<string, boolean>;
  batteryMv: number;
  chargingMv: number;
  temperatureC: number;
  uptimeDays: number;
  acceleration: { x: number; y: number; z: number };
  lrSatellites: number;
  unreadMessage: boolean;
  locked: boolean;
  joinError: boolean;
  hardwareVersion: string;
  firmwareVersion: string;
  hardwareType: number;
  firmwareType: number;
  satelliteEnabled: boolean;
  fenceEnabled: boolean;
  satelliteRetries: number;
}

const mapped = (byte: number) => (byte * 200) / 255 - 100;

/** The 14 data bytes of the status message (research 3.4). */
export function decodeStatus(data: Uint8Array): StatusMessage {
  if (data.length < 14) throw new Error(`status needs 14 bytes, got ${data.length}`);
  const [reset, err, bat, operation, temp, uptime, accX, accY, accZ, hwVer, fwVer, type, chg, features] = data;
  const errorNames = ["lr_module", "ble", "ublox", "accelerometer", "battery", "ublox_fix", "flash", "ublox_busy"];
  return {
    resetReason: { pin: Boolean(reset & 1), watchdog: Boolean(reset & 2), software: Boolean(reset & 4), lockup: Boolean(reset & 8) },
    errors: Object.fromEntries(errorNames.map((name, i) => [name, Boolean(err & (1 << i))])),
    batteryMv: bat * 10 + 2500,
    chargingMv: chg ? chg * 100 + 5000 : 0,
    temperatureC: Math.round(mapped(temp) * 100) / 100,
    uptimeDays: uptime,
    acceleration: { x: Math.round(mapped(accX) * 100) / 100, y: Math.round(mapped(accY) * 100) / 100, z: Math.round(mapped(accZ) * 100) / 100 },
    lrSatellites: operation >> 4,
    unreadMessage: Boolean(operation & 1),
    locked: Boolean(operation & 2),
    joinError: Boolean(operation & 4),
    hardwareVersion: `${hwVer >> 4}.${hwVer & 0x0f}`,
    firmwareVersion: `${fwVer >> 4}.${fwVer & 0x0f}`,
    hardwareType: type & 0x0f,
    firmwareType: type >> 4,
    satelliteEnabled: Boolean(features & 1),
    fenceEnabled: Boolean(features & 4),
    satelliteRetries: features >> 4,
  };
}

/** Flash status data (research 3.12): used percentage and stored message count. */
export function decodeFlashStatus(data: Uint8Array): { usedPercent: number; messages: number } {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  return { usedPercent: data[0], messages: view.getUint32(1, true) };
}

/** A frame as the device sent it: the port byte first. */
export interface Frame { port: number; msgId: number; length: number; data: Uint8Array; raw: Uint8Array; at: Date }

export function parseFrame(raw: Uint8Array, at = new Date()): Frame {
  return { port: raw[0], msgId: raw[1] ?? 0, length: raw[2] ?? 0, data: raw.slice(3, 3 + (raw[2] ?? 0)), raw, at };
}

export function isConfirmation(frame: Frame, cmdId: number): boolean {
  return frame.port === PORT.messages && frame.msgId === MSG.cmdConfirm && frame.data[0] === cmdId;
}

/** What the protocol needs from a link: write a frame, receive frames. */
export interface Transport {
  write(frame: Uint8Array): Promise<void>;
  onFrame(listener: (raw: Uint8Array) => void): () => void;
  onDisconnect?(listener: () => void): () => void;
  disconnect(): Promise<void>;
  name: string;
}

export class TimeoutError extends Error {}

export interface FlashDownload { frames: Uint8Array[]; confirmed: boolean; status: number | null }

/** The protocol on top of a transport: requests with matching answers, collectors for streams. */
export class OpenCollarSession {
  readonly received: Frame[] = [];
  private readonly listeners = new Set<(frame: Frame) => void>();
  private readonly unsubscribe: () => void;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(readonly transport: Transport) {
    this.unsubscribe = transport.onFrame((raw) => {
      if (raw.length === 0) return;
      const frame = parseFrame(raw);
      this.received.push(frame);
      for (const listener of this.listeners) listener(frame);
    });
  }

  get name(): string {
    return this.transport.name;
  }

  /** Every frame received since the last call; the page syncs them to the backend. */
  takeReceived(): Frame[] {
    return this.received.splice(0, this.received.length);
  }

  subscribe(listener: (frame: Frame) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async write(frame: Uint8Array): Promise<void> {
    const next = this.queue.then(() => this.transport.write(frame));
    this.queue = next.catch(() => undefined);
    await next;
  }

  /** Write a frame and resolve with the first frame the matcher accepts, or reject on timeout. */
  async request(frame: Uint8Array, matcher: (frame: Frame) => boolean, timeoutMs = 8000): Promise<Frame> {
    return new Promise<Frame>((resolve, reject) => {
      const timer = setTimeout(() => { stop(); reject(new TimeoutError(`no answer within ${timeoutMs} ms`)); }, timeoutMs);
      const stop = this.subscribe((received) => {
        if (matcher(received)) { clearTimeout(timer); stop(); resolve(received); }
      });
      this.write(frame).catch((error: unknown) => { clearTimeout(timer); stop(); reject(error instanceof Error ? error : new Error(String(error))); });
    });
  }

  async requestStatus(): Promise<StatusMessage> {
    const frame = await this.request(commandFrame(CMD.sendStatus), (f) => f.port === PORT.status && f.msgId === MSG.status);
    return decodeStatus(frame.data);
  }

  async requestFlashStatus(): Promise<{ usedPercent: number; messages: number }> {
    const frame = await this.request(commandFrame(CMD.getFlashStatus), (f) => f.port === PORT.flashStatus && f.msgId === MSG.flashStatus);
    return decodeFlashStatus(frame.data);
  }

  async requestTimestamp(): Promise<Date> {
    const frame = await this.request(commandFrame(CMD.sendTimestamp), (f) => f.port === PORT.timestamp && f.msgId === MSG.timestamp);
    const seconds = new DataView(frame.data.buffer, frame.data.byteOffset).getUint32(0, true);
    return new Date(seconds * 1000);
  }

  /** All settings: the device answers with several port 3 frames and a confirmation (research 3.3). */
  async requestSettings(timeoutMs = 10000): Promise<Map<number, Uint8Array>> {
    const values = new Map<number, Uint8Array>();
    await this.collect(commandFrame(CMD.sendAllSettings), (f) => {
      if (f.port === PORT.settings) for (const item of parseTlv(f.raw.slice(1))) values.set(item.id, item.value);
      return isConfirmation(f, CMD.sendAllSettings);
    }, timeoutMs, 1500);
    return values;
  }

  /** Write one setting; a confirmation is optional, so a quiet second counts as accepted. */
  async writeSetting(setting: CatalogSetting, value: unknown): Promise<boolean | null> {
    const frame = settingFrame(setting.id, encodeSettingValue(setting.type, setting.length, value));
    try {
      const confirm = await this.request(frame, (f) => f.port === PORT.messages && f.msgId === MSG.cmdConfirm, 1000);
      return confirm.data[1] === 1;
    } catch (error) {
      if (error instanceof TimeoutError) return null;
      throw error;
    }
  }

  async sendCommand(cmdId: number, argument = new Uint8Array(0), timeoutMs = 5000): Promise<{ confirmed: boolean | null; status: number | null }> {
    try {
      const confirm = await this.request(commandFrame(cmdId, argument), (f) => isConfirmation(f, cmdId), timeoutMs);
      return { confirmed: confirm.data[1] === 1, status: confirm.data[1] };
    } catch (error) {
      if (error instanceof TimeoutError) return { confirmed: null, status: null };
      throw error;
    }
  }

  /** Stream the flash log (`cmd_flash_get_all`, port 0 = every port) until the confirmation;
   * an idle gap longer than `idleMs` ends the download without confirmation. */
  async downloadLogs(port = 0, onProgress?: (frames: number, bytes: number) => void, idleMs = 15000): Promise<FlashDownload> {
    const frames: Uint8Array[] = [];
    let bytes = 0;
    const result = await this.collect(commandFrame(CMD.flashGetAll, new Uint8Array([port])), (f) => {
      if (f.port === PORT.flashLog) { frames.push(f.raw); bytes += f.raw.length; onProgress?.(frames.length, bytes); return false; }
      return isConfirmation(f, CMD.flashGetAll);
    }, 24 * 3600 * 1000, idleMs);
    return { frames, confirmed: result !== null, status: result?.data[1] ?? null };
  }

  async eraseLogs(): Promise<boolean> {
    const confirm = await this.request(commandFrame(CMD.flashClear), (f) => isConfirmation(f, CMD.flashClear), 20000);
    return confirm.data[1] === 1;
  }

  /** Write any frame the backend encoded (a command over the WebBLE route, decision D79) and
   * wait briefly for a confirmation on port 31. */
  async writeEncoded(frame: Uint8Array, timeoutMs = 3000): Promise<Frame | null> {
    const cmdId = frame[0] === PORT.commands ? frame[1] : null;
    try {
      return await this.request(frame, (f) => (cmdId === null ? f.port === PORT.messages && f.msgId === MSG.cmdConfirm : isConfirmation(f, cmdId)), timeoutMs);
    } catch (error) {
      if (error instanceof TimeoutError) return null;
      throw error;
    }
  }

  async disconnect(): Promise<void> {
    this.unsubscribe();
    await this.transport.disconnect();
  }

  /** Write, then feed every frame to `step` until it returns true (done) or the link stays idle. */
  private collect(frame: Uint8Array, step: (frame: Frame) => boolean, timeoutMs: number, idleMs: number): Promise<Frame | null> {
    return new Promise<Frame | null>((resolve, reject) => {
      let idle: ReturnType<typeof setTimeout> | null = null;
      const total = setTimeout(() => finish(null), timeoutMs);
      const armIdle = () => { if (idle) clearTimeout(idle); idle = setTimeout(() => finish(null), idleMs); };
      const stop = this.subscribe((received) => {
        armIdle();
        if (step(received)) finish(received);
      });
      const finish = (value: Frame | null) => { clearTimeout(total); if (idle) clearTimeout(idle); stop(); resolve(value); };
      armIdle();
      this.write(frame).catch((error: unknown) => { finish(null); reject(error instanceof Error ? error : new Error(String(error))); });
    });
  }
}

// Web Bluetooth. The DOM lib does not type it; the subset used here is declared structurally.

interface GattCharacteristicLike {
  writeValueWithResponse?(value: BufferSource): Promise<void>;
  writeValueWithoutResponse?(value: BufferSource): Promise<void>;
  writeValue(value: BufferSource): Promise<void>;
  startNotifications(): Promise<unknown>;
  addEventListener(type: "characteristicvaluechanged", listener: (event: { target: { value?: DataView } }) => void): void;
}
interface GattServiceLike { getCharacteristic(uuid: string): Promise<GattCharacteristicLike> }
interface GattServerLike { connect(): Promise<GattServerLike>; disconnect(): void; getPrimaryService(uuid: string): Promise<GattServiceLike>; connected: boolean }
interface BluetoothDeviceLike { name?: string; id: string; gatt?: GattServerLike; addEventListener(type: "gattserverdisconnected", listener: () => void): void }
interface BluetoothLike { requestDevice(options: unknown): Promise<BluetoothDeviceLike> }

export function webBluetoothAvailable(): boolean {
  return typeof navigator !== "undefined" && "bluetooth" in navigator && window.isSecureContext;
}

/** Let the person pick a device (chooser filtered on the Smart Parks manufacturer id or the
 * UART service), connect and wire the characteristics. */
export async function connectWebBluetooth(namePrefix?: string): Promise<Transport> {
  const bluetooth = (navigator as unknown as { bluetooth?: BluetoothLike }).bluetooth;
  if (!bluetooth) throw new Error("Web Bluetooth is not available in this browser; use Chrome or Edge over HTTPS.");
  const filters: unknown[] = [{ manufacturerData: [{ companyIdentifier: MANUFACTURER_ID }] }, { services: [NUS_SERVICE] }];
  if (namePrefix) filters.push({ namePrefix });
  const device = await bluetooth.requestDevice({ filters, optionalServices: [NUS_SERVICE] });
  if (!device.gatt) throw new Error("The chosen device has no GATT server.");
  const server = await device.gatt.connect();
  const service = await server.getPrimaryService(NUS_SERVICE);
  const tx = await service.getCharacteristic(NUS_TX);
  const rx = await service.getCharacteristic(NUS_RX);
  const frameListeners = new Set<(raw: Uint8Array) => void>();
  const disconnectListeners = new Set<() => void>();
  tx.addEventListener("characteristicvaluechanged", (event) => {
    const value = event.target.value;
    if (!value) return;
    const raw = new Uint8Array(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength));
    for (const listener of frameListeners) listener(raw);
  });
  await tx.startNotifications();
  device.addEventListener("gattserverdisconnected", () => { for (const listener of disconnectListeners) listener(); });
  return {
    name: device.name ?? device.id,
    async write(frame) {
      const buffer = frame.slice().buffer as ArrayBuffer;
      if (rx.writeValueWithResponse) await rx.writeValueWithResponse(buffer);
      else if (rx.writeValueWithoutResponse) await rx.writeValueWithoutResponse(buffer);
      else await rx.writeValue(buffer);
    },
    onFrame(listener) { frameListeners.add(listener); return () => frameListeners.delete(listener); },
    onDisconnect(listener) { disconnectListeners.add(listener); return () => disconnectListeners.delete(listener); },
    async disconnect() { if (server.connected) server.disconnect(); },
  };
}
