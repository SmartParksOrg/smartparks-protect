import { beforeEach, describe, expect, it } from "vitest";

import {
  forgetProjects,
  isProjectSwitch,
  rememberProject,
} from "@/components/map/mapSession";

describe("the map's memory of the project it opened", () => {
  beforeEach(() => forgetProjects());

  it("counts a fresh page as coming back, not as a switch", () => {
    // the map_view preference opens the map where the person left it (2026-09-20)
    expect(isProjectSwitch("pwn")).toBe(false);
  });

  it("counts another project as a switch, and the same one as coming back", () => {
    rememberProject("pwn");
    expect(isProjectSwitch("pwn")).toBe(false);
    expect(isProjectSwitch("okonjima")).toBe(true);
    rememberProject("okonjima");
    expect(isProjectSwitch("okonjima")).toBe(false);
    expect(isProjectSwitch("pwn")).toBe(true);
  });

  it("forgets on a reload, so the remembered view wins again", () => {
    rememberProject("pwn");
    forgetProjects();
    expect(isProjectSwitch("okonjima")).toBe(false);
  });
});
