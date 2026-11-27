import { describe, expect, it } from "vitest";

import {
  buildPanels,
  type FieldRow,
  type GroupRow,
  KNOWN_CONTROLS,
  type MatrixRow,
  settingsOfFirmware,
  type Row,
} from "@/lib/settingsPanels";
import {
  type PanelField,
  panels,
  settingsMeta,
} from "@/vendor/ble-settings-app";
import licence from "@/vendor/ble-settings-app/LICENSE-MIT-panels.md?raw";
import definitionsText from "@/vendor/ble-settings-app/panel-definitions.js?raw";
import engineText from "@/vendor/ble-settings-app/panel-engine.js?raw";
import pin from "@/vendor/ble-settings-app/pin.json";
import metaText from "@/vendor/ble-settings-app/settings-meta.json?raw";

// the driver's catalogues, cut to what the topics read; a Python test keeps the fixture the
// driver's (tests/shared/test_frontend_catalogue_fixture.py)
import catalogues from "@/test/fixtures/opencollar-catalogues.json";

const COPIES: Record<string, string> = {
  "settings-meta.json": metaText,
  "panel-definitions.js": definitionsText,
  "panel-engine.js": engineText,
  "LICENSE-MIT-panels.md": licence,
};

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

interface CatalogSetting {
  name: string;
  type: string;
  default: unknown;
}

interface CatalogDocument {
  settings: CatalogSetting[];
  ports: Record<string, number>;
  families?: boolean;
}

const CATALOGUES: Record<string, CatalogDocument> = {
  "catalog.json": catalogues.v7 as unknown as CatalogDocument,
  "catalog-v8.json": catalogues.v8 as unknown as CatalogDocument,
};

function catalogue(file: string): CatalogDocument {
  return CATALOGUES[file];
}

/** A device that reports the firmware's defaults, with what is given changed. */
function context(
  file: string,
  firmware: string,
  values: Record<string, unknown> = {},
) {
  const document = catalogue(file);
  return {
    settings: document.settings.map((s) => ({
      key: s.name,
      type: s.type,
      value: s.name in values ? values[s.name] : s.default,
    })),
    families: Boolean(document.families),
    ports: document.ports,
    firmware,
  };
}

function fields(rows: Row[]): FieldRow[] {
  return rows.flatMap((row) =>
    row.kind === "group" ? fields(row.rows) : row.kind === "field" ? [row] : [],
  );
}

describe("the ble-settings-app's files in Protect", () => {
  it("are the files of the pinned commit, byte for byte", async () => {
    expect(pin.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(Object.keys(pin.files).sort()).toEqual(Object.keys(COPIES).sort());
    for (const [name, sha] of Object.entries(pin.files))
      expect(
        await sha256(COPIES[name]),
        `${name} was edited here; change it in the app and run scripts/sync_settings_panels.py`,
      ).toBe(sha);
  });

  it("use no control Protect's reading does not know", () => {
    const controls = new Set<string>();
    const walk = (list: PanelField[]) => {
      for (const field of list) {
        if (field.control) controls.add(field.control);
        if (field.fields) walk(field.fields);
      }
    };
    for (const panel of panels) walk(panel.fields);
    expect([...controls].filter((c) => !KNOWN_CONTROLS.has(c))).toEqual([]);
  });

  it("name every setting of both catalogues", () => {
    for (const file of ["catalog.json", "catalog-v8.json"])
      expect(
        catalogue(file)
          .settings.map((s) => s.name)
          .filter((name) => !settingsMeta[name]?.display_name),
      ).toEqual([]);
  });
});

describe("a device's settings by topic", () => {
  it("says each topic in a sentence when every value is known", () => {
    const views = buildPanels(
      context("catalog-v8.json", "8.0", {
        ublox_send_interval: 900,
        device_name: "SP051463",
        status_send_interval: 3600,
      }),
    );
    const byId = Object.fromEntries(views.map((v) => [v.id, v]));
    expect(byId.positioning.summary).toContain("15 minutes");
    expect(byId.device.summary).toContain("SP051463.");
    expect(byId.device.summary).toContain("Status report every 1 hour.");
    expect(byId.network.summary).not.toBe("");
    expect(byId.data.summary).not.toBe("");
    expect(byId.positioning.known).toBe(byId.positioning.total);
    // a topic without a sentence of its own says its switch
    expect(byId["wifi-scanning"].summary).toBe("Scan: off.");
    // LP0 offload is firmware 8.1 and later
    expect(byId.lp0).toBeUndefined();
    expect(
      buildPanels(context("catalog-v8.json", "8.2")).some((v) => v.id === "lp0"),
    ).toBe(true);
  });

  it("writes values in words and greys out what has no meaning now", () => {
    const views = buildPanels(
      context("catalog-v8.json", "8.0", {
        ublox_send_interval: 900,
        ublox_multiple_intervals: false,
        ublox_send_interval_2: 0,
        lr_region: 1,
        lr_adr_profile: 0,
        lr_adr: 5,
        app_key: "8bcd49421167dd03bad3aeea98efe409",
        device_pin: "01020304",
        device_eui: "0000000000000000",
      }),
    );
    const positioning = fields(views.find((v) => v.id === "positioning")!.rows);
    const row = (label: string, list = positioning) =>
      list.find((f) => f.label === label)!;
    expect(row("Scheduled fixes").value).toBe("On");
    expect(row("Schedule type").value).toBe("Fixed interval");
    expect(row("Fix interval").value).toBe("15 minutes");
    expect(row("Fix interval").keys).toEqual(["ublox_send_interval"]);
    expect(row("Night interval").inactive).toBe(true);
    expect(row("Night interval").reason).toBe(
      "Only used with the day and night schedule.",
    );
    expect(row("Night interval").value).toBe("No fixes at night");
    const network = fields(views.find((v) => v.id === "network")!.rows);
    expect(row("Region", network).value).toBe("EU 868");
    expect(row("Data rate", network).value).toBe("DR5 = SF7 / 125 kHz");
    expect(row("Data rate", network).inactive).toBe(true);
    expect(row("App key", network).value).toBe("Set (hidden)");
    expect(row("Device EUI", network).warnings).toHaveLength(1);
    const device = fields(views.find((v) => v.id === "device")!.rows);
    expect(row("Bluetooth PIN", device).value).toBe("Set");
  });

  it("draws the message types as a table of ticks", () => {
    const data = buildPanels(
      context("catalog-v8.json", "8.0", { lr_send_flag: 0b1010, sat_send_flag: 0 }),
    ).find((v) => v.id === "data")!;
    const matrix = data.rows.find((r) => r.kind === "matrix") as MatrixRow;
    expect(matrix.columns.map((c) => c.label)).toEqual([
      "LoRaWAN",
      "Satellite",
      "LP0",
      "Store",
    ]);
    const status = matrix.ports.find((p) => p.number === 4)!;
    expect(status.label).toBe("Status report");
    expect(status.set.slice(0, 2)).toEqual([true, false]);
    expect(matrix.ports.find((p) => p.number === 1)!.set[0]).toBe(false);
    // ports without a message type of their own are no rows
    expect(matrix.ports.some((p) => p.number === 32)).toBe(false);
  });

  it("keeps quiet about a topic it does not know whole", () => {
    const partial = context("catalog-v8.json", "8.0");
    for (const s of partial.settings)
      s.value = s.key === "ublox_send_interval" ? 300 : null;
    const positioning = buildPanels(partial).find((v) => v.id === "positioning")!;
    expect(positioning.summary).toBe("");
    expect(positioning.known).toBe(1);
    const rows = fields(positioning.rows);
    expect(rows.find((f) => f.label === "Fix interval")!.value).toBe("5 minutes");
    expect(rows.find((f) => f.label === "Active tracking")!.value).toBeNull();
    // nothing is greyed out for a reason Protect cannot know
    expect(rows.every((f) => !f.inactive)).toBe(true);
  });

  it("leaves out what a firmware 7 device does not have", () => {
    const views = buildPanels(context("catalog.json", "7.2"));
    const all = views.flatMap((v) => fields(v.rows));
    expect(all.some((f) => f.keys.includes("lr_enabled"))).toBe(false);
    expect(views.find((v) => v.id === "positioning")!.summary).not.toBe("");
    const groups = views
      .find((v) => v.id === "positioning")!
      .rows.filter((r): r is GroupRow => r.kind === "group");
    expect(groups.map((g) => g.title)).toContain("Advanced fix settings");
  });

  it("does not wait for settings that came after the device's firmware", () => {
    const settings = [
      { key: "lr_region", type: "uint8", value: 1, since_firmware: "4.4.2" },
      { key: "lr_enabled", type: "bool", value: null, since_firmware: "8.2.0" },
      { key: "lp0_master_key", type: "byte_array", value: null, since_firmware: "8.1.0" },
    ];
    const keys = (firmware: string | null) =>
      settingsOfFirmware(settings, firmware).map((s) => s.key);
    expect(keys("8.0")).toEqual(["lr_region"]);
    expect(keys("8.1")).toEqual(["lr_region", "lp0_master_key"]);
    expect(keys("8.2")).toHaveLength(3);
    expect(keys(null)).toHaveLength(3);
    // a device that reports it has it, whatever its status says
    settings[1].value = true as never;
    expect(keys("8.0")).toEqual(["lr_region", "lr_enabled"]);
  });
});
