import { beforeEach, describe, expect, it } from "vitest";

import {
  buildMoved,
  forgetBuild,
  loadedBuild,
  rememberBuild,
} from "@/lib/build";

describe("whether the tab is older than the server", () => {
  const build = (commit: string) => ({ version: "v2.9.0", commit });

  it("says nothing until there is something to compare", () => {
    expect(buildMoved(null, build("abc1234"))).toBe(false);
    expect(buildMoved(build("abc1234"), null)).toBe(false);
    expect(buildMoved(build("abc1234"), undefined)).toBe(false);
  });

  it("says nothing while the server stays where it was", () => {
    expect(buildMoved(build("abc1234"), build("abc1234"))).toBe(false);
  });

  it("says so when the server has moved on", () => {
    expect(buildMoved(build("abc1234"), build("def5678"))).toBe(true);
  });

  it("holds its tongue where the commit is not known", () => {
    // a development run, or a server without GIT_COMMIT: never nag about that
    expect(buildMoved(build("unknown"), build("def5678"))).toBe(false);
    expect(buildMoved(build("abc1234"), build("unknown"))).toBe(false);
    expect(buildMoved(build(""), build("def5678"))).toBe(false);
  });
});

describe("the build this tab loaded with", () => {
  beforeEach(() => forgetBuild());

  it("is the first answer, and stays it however often the server moves", () => {
    expect(loadedBuild()).toBeNull();
    const first = { version: "v2.9.0", commit: "abc1234" };
    expect(rememberBuild(first)).toEqual(first);
    expect(loadedBuild()).toEqual(first);
    rememberBuild({ version: "v2.10.0", commit: "def5678" });
    expect(loadedBuild()).toEqual(first);
    expect(
      buildMoved(loadedBuild(), { version: "v2.10.0", commit: "def5678" }),
    ).toBe(true);
  });

  it("is gone after a reload, so the new page starts even", () => {
    rememberBuild({ version: "v2.9.0", commit: "abc1234" });
    forgetBuild();
    expect(loadedBuild()).toBeNull();
    expect(
      buildMoved(loadedBuild(), { version: "v2.10.0", commit: "def5678" }),
    ).toBe(false);
  });
});
