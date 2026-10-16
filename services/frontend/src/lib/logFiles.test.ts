import { describe, expect, it } from "vitest";

import type { DeviceLogFile } from "@/api/types";
import { folderOf, kindOf, percentDone, sizeLabel, summaryOf } from "@/lib/logFiles";

const t = ((key: string, options?: Record<string, unknown>) =>
  options
    ? key.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name]))
    : key) as never;

function file(overrides: Partial<DeviceLogFile> = {}): DeviceLogFile {
  return {
    id: "f1",
    device_id: "d1",
    project_id: null,
    data_source_id: "s1",
    acquisition_channel: "lp0",
    original_filename: "0016C001F0500101_1789578300.jsonl",
    sha256: "x",
    size_bytes: 20_480,
    uploaded_by_user_id: null,
    uploaded_at: "2026-10-16T12:00:00Z",
    ble_synced_at: null,
    status: "complete",
    error_code: null,
    error_message: null,
    frames_total: 18,
    frames_done: 18,
    frames_failed: 0,
    records_found: 100,
    records_new: 96,
    records_duplicate: 4,
    period_start: null,
    period_end: null,
    firmware_version: null,
    decoder_version: null,
    trace_id: null,
    processed_at: null,
    attributes: { folder: "LOG_1" },
    created_at: "2026-10-16T12:00:00Z",
    updated_at: "2026-10-16T12:00:00Z",
    ...overrides,
  } as DeviceLogFile;
}

describe("the log files explorer's helpers", () => {
  it("names the kind by the channel", () => {
    expect(kindOf("lp0")).toBe("station_card");
    expect(kindOf("webble")).toBe("browser_sync");
    expect(kindOf("log_file")).toBe("raw_log");
    expect(kindOf("iridium")).toBe("other");
  });

  it("reads the folder, the size and the progress", () => {
    expect(folderOf(file())).toBe("LOG_1");
    expect(folderOf(file({ attributes: {} }))).toBeNull();
    expect(sizeLabel(20_480)).toBe("20 kB");
    expect(sizeLabel(300)).toBe("1 kB");
    expect(sizeLabel(2.5 * 1024 * 1024)).toBe("2.5 MB");
    expect(percentDone(file({ status: "processing", frames_done: 9 }))).toBe(50);
    expect(percentDone(file({ status: "processing", frames_total: 0 }))).toBeNull();
  });

  it("sums a file up in one line", () => {
    expect(summaryOf(file(), t)).toBe("18 frames, 96 new records, 4 known");
    expect(summaryOf(file({ records_duplicate: 0, frames_failed: 2 }), t)).toBe(
      "18 frames, 96 new records, 2 failed",
    );
    expect(summaryOf(file({ status: "queued" }), t)).toBe("waiting for the decoder");
    expect(summaryOf(file({ status: "processing", frames_done: 9 }), t)).toBe(
      "9 of 18 frames decoded, 50%",
    );
    expect(summaryOf(file({ status: "processing", frames_total: 0 }), t)).toBe("reading the file");
    expect(summaryOf(file({ status: "failed", error_message: "not a log" }), t)).toBe("not a log");
  });
});
