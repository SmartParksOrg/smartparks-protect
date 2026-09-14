import { describe, expect, it } from "vitest";

import { sectionsFor } from "@/components/layout/navigation";

describe("navigation sections", () => {
  it("keeps the Network section for admins and the rest for everyone (decision D134)", () => {
    const sections = sectionsFor(false);
    const byLabel = Object.fromEntries(sections.map((s) => [s.label, s]));
    expect(byLabel.Network.permission).toBe("project:write");
    expect(byLabel.Monitor.permission).toBeUndefined();
    expect(byLabel.Analyze.permission).toBeUndefined();
    expect(sections.some((s) => "technical" in s)).toBe(false);
  });
});

describe("analysis items", () => {
  it("carry the module that must be offered and no permission (plan, section 16)", () => {
    const analyze = sectionsFor(false).find((s) => s.label === "Analyze");
    const movement = analyze?.items.find((i) => i.to === "analyze/movement");
    const grazing = analyze?.items.find((i) => i.to === "analyze/grazing");
    expect(movement?.module).toBe("movement");
    expect(grazing?.module).toBe("grazing");
    expect(movement?.permission).toBeUndefined();
    expect(sectionsFor(true).find((s) => s.label === "Analyze")?.items.some((i) => i.module)).toBeFalsy();
  });
});
