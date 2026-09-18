import { afterEach, describe, expect, it } from "vitest";

import { portalContainer } from "@/lib/portalContainer";

afterEach(() => {
  Object.defineProperty(document, "fullscreenElement", {
    value: null,
    configurable: true,
  });
});

describe("where a floating menu is rendered", () => {
  it("leaves the default alone with nothing full screen", () => {
    expect(portalContainer()).toBeUndefined();
  });

  it("puts it inside the full-screen element, which is the only painted subtree", () => {
    const frame = document.createElement("div");
    document.body.append(frame);
    Object.defineProperty(document, "fullscreenElement", {
      value: frame,
      configurable: true,
    });
    expect(portalContainer()).toBe(frame);
  });
});
