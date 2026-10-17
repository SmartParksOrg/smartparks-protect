/** Protect Go, the app for the laptop (decision D332; named Protect Go on 2026-10-17): the installers of its newest
 * release under fixed names, the one for the visitor's system first, and the link that opens an
 * installed Protect Go connected to this server. */

export type FieldSystem = "windows" | "macos" | "linux";

export interface FieldInstaller {
  system: FieldSystem;
  label: string;
  note: string;
  file: string;
  url: string;
}

const RELEASE = "https://github.com/SmartParksOrg/smartparks-protect-go/releases/latest/download";
export const FIELD_GUIDE_URL = "https://smartparksorg.github.io/smartparks-protect-go/using-protect-go/";

const INSTALLERS: Record<FieldSystem, Omit<FieldInstaller, "url">> = {
  windows: { system: "windows", label: "Windows", note: "Windows 10 and 11", file: "ProtectGo-Setup.exe" },
  macos: { system: "macos", label: "macOS", note: "Apple Silicon", file: "ProtectGo-arm64.dmg" },
  linux: { system: "linux", label: "Linux", note: "Debian and Ubuntu", file: "ProtectGo-amd64.deb" },
};

/** The visitor's system from the user agent, or null for a phone or something else. */
export function detectSystem(userAgent: string): FieldSystem | null {
  const ua = userAgent.toLowerCase();
  if (/android|iphone|ipad|ipod/.test(ua)) return null;
  if (ua.includes("windows")) return "windows";
  if (ua.includes("mac os") || ua.includes("macintosh")) return "macos";
  if (ua.includes("linux") || ua.includes("x11")) return "linux";
  return null;
}

/** The installers, the visitor's system first when it is known. */
export function fieldInstallers(system: FieldSystem | null): FieldInstaller[] {
  const order: FieldSystem[] = ["windows", "macos", "linux"];
  if (system) {
    order.splice(order.indexOf(system), 1);
    order.unshift(system);
  }
  return order.map((key) => ({ ...INSTALLERS[key], url: `${RELEASE}/${INSTALLERS[key].file}` }));
}

/** The link an installed Protect Go answers to: the app opens with this server filled in. */
export function fieldConnectLink(serverOrigin: string): string {
  return `protect-go://connect?server=${encodeURIComponent(serverOrigin)}`;
}
