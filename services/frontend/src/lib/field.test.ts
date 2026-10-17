import { detectSystem, fieldConnectLink, fieldInstallers } from "@/lib/field";

test("detects the visitor's system and leaves phones out", () => {
  expect(detectSystem("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("windows");
  expect(detectSystem("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")).toBe("macos");
  expect(detectSystem("Mozilla/5.0 (X11; Linux x86_64)")).toBe("linux");
  expect(detectSystem("Mozilla/5.0 (Linux; Android 14; Pixel 7)")).toBeNull();
  expect(detectSystem("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")).toBeNull();
});

test("puts the visitor's installer first with the fixed release names", () => {
  const forMac = fieldInstallers("macos");
  expect(forMac.map((i) => i.system)).toEqual(["macos", "windows", "linux"]);
  expect(forMac[0].url).toBe(
    "https://github.com/SmartParksOrg/smartparks-protect-field/releases/latest/download/ProtectField-arm64.dmg",
  );
  expect(fieldInstallers(null).map((i) => i.file)).toEqual([
    "ProtectField-Setup.exe",
    "ProtectField-arm64.dmg",
    "ProtectField-amd64.deb",
  ]);
});

test("the connect link carries the server", () => {
  expect(fieldConnectLink("https://dev-protect.smartparks.org")).toBe(
    "protect-field://connect?server=https%3A%2F%2Fdev-protect.smartparks.org",
  );
});
