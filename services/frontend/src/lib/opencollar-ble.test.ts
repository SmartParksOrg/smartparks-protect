import { describe, expect, it } from "vitest";

import {
  CMD,
  commandFrame,
  decodeSettingValue,
  decodeStatus,
  encodeSettingValue,
  fromHex,
  hex,
  isConfirmation,
  OpenCollarSession,
  parseFrame,
  parseTlv,
  PORT,
  settingFrame,
  toBase64,
  type Transport,
} from "@/lib/opencollar-ble";

/** A device that answers from a script: frames to emit per written command id. */
function fakeTransport(script: (frame: Uint8Array, emit: (raw: Uint8Array) => void) => void): Transport & { written: Uint8Array[] } {
  const listeners = new Set<(raw: Uint8Array) => void>();
  const written: Uint8Array[] = [];
  return {
    name: "SP05-test",
    written,
    async write(frame) {
      written.push(frame);
      queueMicrotask(() => script(frame, (raw) => { for (const l of listeners) l(raw); }));
    },
    onFrame(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    async disconnect() { /* nothing to close */ },
  };
}

describe("OpenCollar BLE framing", () => {
  it("builds command and setting frames with the port in front (research 4.1, 4.2, 4.5)", () => {
    expect(hex(commandFrame(CMD.sendStatus))).toBe("20a400");
    expect(hex(commandFrame(CMD.flashGetAll, new Uint8Array([0])))).toBe("20bb0100");
    // the wiki example: set ublox_send_interval to 3600 s is `02 04 10 0E 00 00`, over BLE with port 3 first
    expect(hex(settingFrame(0x02, encodeSettingValue("uint32", 4, 3600)))).toBe("030204100e0000");
    expect(hex(settingFrame(0x3f, encodeSettingValue("bool", 1, true)))).toBe("033f0101");
  });

  it("encodes and decodes every setting type little-endian", () => {
    expect(hex(encodeSettingValue("int32", 4, -1))).toBe("ffffffff");
    expect(decodeSettingValue("int32", fromHex("ffffffff"))).toBe(-1);
    expect(decodeSettingValue("uint16", fromHex("0e10"))).toBe(4110);
    expect(hex(encodeSettingValue("uint16", 2, 4110))).toBe("0e10");
    expect(decodeSettingValue("byte_array", encodeSettingValue("byte_array", 4, "260bf6ef"))).toBe("260bf6ef");
    expect(decodeSettingValue("string", encodeSettingValue("string", 8, "SP05"))).toBe("SP05");
    expect(decodeSettingValue("bool", encodeSettingValue("bool", 1, false))).toBe(false);
    expect(() => encodeSettingValue("byte_array", 4, "26")).toThrow();
    expect(() => encodeSettingValue("uint8", 1, "x")).toThrow();
  });

  it("decodes the wiki status example (research 3.4)", () => {
    const status = decodeStatus(fromHex("0400a00095007f7f721444550000"));
    expect(status.batteryMv).toBe(4100);
    expect(status.chargingMv).toBe(0);
    expect(status.temperatureC).toBeCloseTo(16.86, 1);
    expect(status.acceleration.z).toBeCloseTo(-10.59, 1);
    expect(status.firmwareVersion).toBe("4.4");
    expect(status.hardwareVersion).toBe("1.4");
    expect(status.hardwareType).toBe(5);
    expect(status.firmwareType).toBe(5);
    expect(status.resetReason.software).toBe(true);
    expect(Object.values(status.errors).some(Boolean)).toBe(false);
  });

  it("parses TLV lists and confirmation frames", () => {
    expect(parseTlv(fromHex("020410 0e0000 3f0101".replace(/ /g, "")))).toEqual([
      { id: 2, value: fromHex("100e0000") },
      { id: 0x3f, value: fromHex("01") },
    ]);
    const confirm = parseFrame(fromHex("1ff302bb01"));
    expect(confirm.port).toBe(PORT.messages);
    expect(isConfirmation(confirm, CMD.flashGetAll)).toBe(true);
    expect(isConfirmation(confirm, CMD.flashClear)).toBe(false);
    expect(toBase64(fromHex("1d0d930e"))).toBe("HQ2TDg==");
  });
});

describe("OpenCollar BLE session", () => {
  it("answers a status request and keeps every received frame for the sync", async () => {
    const transport = fakeTransport((frame, emit) => {
      if (frame[1] === CMD.sendStatus) emit(fromHex("04f40e0400a00095007f7f721444550000"));
    });
    const session = new OpenCollarSession(transport);
    const status = await session.requestStatus();
    expect(status.firmwareVersion).toBe("4.4");
    const frames = session.takeReceived();
    expect(frames).toHaveLength(1);
    expect(hex(frames[0].raw)).toBe("04f40e0400a00095007f7f721444550000");
    expect(session.takeReceived()).toHaveLength(0);
  });

  it("collects flash log frames until the confirmation", async () => {
    const record = "0d930e3c636865fca10d1f7d160e030c0043636865";
    const transport = fakeTransport((frame, emit) => {
      if (frame[1] === CMD.flashGetAll) {
        emit(fromHex("1d" + record));
        emit(fromHex("1d" + record));
        emit(fromHex("1ff302bb01"));
      }
    });
    const session = new OpenCollarSession(transport);
    const progress: number[] = [];
    const download = await session.downloadLogs(0, (n) => progress.push(n));
    expect(download.confirmed).toBe(true);
    expect(download.status).toBe(1);
    expect(download.frames).toHaveLength(2);
    expect(progress).toEqual([1, 2]);
    expect(hex(transport.written[0])).toBe("20bb0100");
  });

  it("ends a download on an idle link without confirmation", async () => {
    const transport = fakeTransport((frame, emit) => {
      if (frame[1] === CMD.flashGetAll) emit(fromHex("1d0d930e3c636865fca10d1f7d160e030c0043636865"));
    });
    const session = new OpenCollarSession(transport);
    const download = await session.downloadLogs(0, undefined, 30);
    expect(download.confirmed).toBe(false);
    expect(download.frames).toHaveLength(1);
  });

  it("reads all settings from several port 3 frames closed by a confirmation", async () => {
    const transport = fakeTransport((frame, emit) => {
      if (frame[1] === CMD.sendAllSettings) {
        emit(fromHex("03" + "0204100e0000"));
        emit(fromHex("03" + "3f0101" + "000105"));
        emit(fromHex("1ff302a701"));
      }
    });
    const session = new OpenCollarSession(transport);
    const settings = await session.requestSettings();
    expect(settings.size).toBe(3);
    expect(decodeSettingValue("uint32", settings.get(2)!)).toBe(3600);
    expect(decodeSettingValue("uint8", settings.get(0)!)).toBe(5);
  });

  it("treats a silent setting write as accepted without confirmation", async () => {
    const transport = fakeTransport(() => undefined);
    const session = new OpenCollarSession(transport);
    const result = await session.writeSetting({ id: 2, name: "ublox_send_interval", length: 4, type: "uint32", default: 0, min: 0, max: 172800 }, 60);
    expect(result).toBeNull();
    expect(hex(transport.written[0])).toBe("0302043c000000");
  });
});
