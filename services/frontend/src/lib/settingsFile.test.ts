import { describe, expect, it } from "vitest";

import { compareFile, exportedAt, fileValue } from "@/lib/settingsFile";

describe("the ble-settings-app's settings file in the browser", () => {
  it("brings a file's value to the form Protect keeps", () => {
    expect(fileValue("app_key", "byte_array", "8BCD49421167DD03")).toBe(
      "8bcd49421167dd03",
    );
    expect(fileValue("app_key", "byte_array", "{0x8B, 0xCD}")).toBe("8bcd");
    expect(fileValue("device_pin", "byte_array", "1234")).toBe("01020304");
    expect(fileValue("device_pin", "byte_array", "0A0B0C0D")).toBe("0a0b0c0d");
    expect(fileValue("led_enabled", "bool", false)).toBe(false);
    expect(fileValue("led_enabled", "bool", "true")).toBe(true);
    expect(fileValue("led_enabled", "bool", "maybe")).toBeUndefined();
    expect(fileValue("ublox_send_interval", "uint32", "900")).toBe(900);
    expect(fileValue("ublox_send_interval", "uint32", "")).toBeUndefined();
    expect(fileValue("device_name", "string", "SP051463")).toBe("SP051463");
  });

  it("reads the export time from the app's file name", () => {
    const now = new Date(2026, 10, 27, 12, 0, 0);
    expect(exportedAt("SP051463_20261127_101500.json", now)).toEqual(
      new Date(2026, 10, 27, 10, 15, 0),
    );
    expect(exportedAt("SP051463_20261127_130000.json", now)).toBeNull();
    expect(exportedAt("my settings.json", now)).toBeNull();
    expect(exportedAt("SP_20261340_101500.json", now)).toBeNull();
  });

  it("compares a file with what Protect knows", () => {
    const comparison = compareFile(
      {
        ublox_send_interval: 900,
        led_enabled: false,
        app_key: "8BCD",
        status_send_interval: 3600,
        no_such_setting: 1,
      },
      [
        { key: "status_send_interval", type: "uint32", value: 3600 },
        { key: "ublox_send_interval", type: "uint32", value: 300 },
        { key: "led_enabled", type: "bool", value: null },
        { key: "app_key", type: "byte_array", value: "8bcd" },
        { key: "gps_resend_interval", type: "uint32", value: 0 },
      ],
    );
    expect(comparison.same).toBe(2);
    expect(comparison.unknown).toEqual(["no_such_setting"]);
    expect(comparison.different).toEqual([
      { key: "ublox_send_interval", type: "uint32", file: 900, known: 300 },
      { key: "led_enabled", type: "bool", file: false, known: null },
    ]);
  });
});
