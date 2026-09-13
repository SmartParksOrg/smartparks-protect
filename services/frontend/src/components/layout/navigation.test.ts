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
