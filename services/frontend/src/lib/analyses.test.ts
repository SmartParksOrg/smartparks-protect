import { describe, expect, it } from "vitest";

import {
  comparisonOf,
  documentOf,
  isActive,
  readFormState,
  windowOf,
  writeFormState,
} from "./analyses";

describe("analysis form state", () => {
  it("round-trips through the URL and writes only what differs from the defaults", () => {
    const state = readFormState(
      new URLSearchParams("entity=a&entity=b&range=7d&compare=previous&run=r1"),
    );
    expect(state.entities).toEqual(["a", "b"]);
    expect(state.range).toBe("7d");
    expect(writeFormState(state).toString()).toBe(
      "entity=a&entity=b&range=7d&compare=previous&run=r1",
    );
    expect(
      writeFormState(readFormState(new URLSearchParams())).toString(),
    ).toBe("");
  });
  it("gives a window for a preset and a comparison right before it", () => {
    const now = new Date("2026-09-14T10:17:42Z");
    const window = windowOf(
      readFormState(new URLSearchParams("range=7d")),
      now,
    );
    expect(window).toEqual({
      time_from: "2026-09-07T10:17:00.000Z",
      time_to: "2026-09-14T10:17:00.000Z",
    });
    const before = comparisonOf(
      readFormState(new URLSearchParams("range=7d&compare=previous")),
      window,
    );
    expect(before).toEqual({
      time_from: "2026-08-31T10:17:00.000Z",
      time_to: "2026-09-07T10:17:00.000Z",
    });
    expect(
      windowOf(readFormState(new URLSearchParams("range=custom")), now),
    ).toBeNull();
  });
  it("reads a result document only at the version it knows", () => {
    expect(documentOf(undefined)).toBeNull();
    expect(documentOf({ result: { version: 2 } } as never)).toBeNull();
    expect(
      documentOf({ result: { version: 1, module: "movement" } } as never)
        ?.module,
    ).toBe("movement");
    expect(isActive("running")).toBe(true);
    expect(isActive("completed")).toBe(false);
  });
});
