/** What a device type's driver can do, as the API lists it on the type (decision D377): the
 * pages show a feature only to the devices whose driver has it, so an AWT tag gets no raw log
 * upload and an OpenCollar no AWT settings. */
export type Capable = { driver_capabilities?: string[] } | null | undefined;

export function hasCapability(type: Capable, capability: string): boolean {
  return Boolean(type?.driver_capabilities?.includes(capability));
}

/** Raw log files and Bluetooth syncs: the device keeps a flash log that can be read out. */
export function supportsRawLogs(type: Capable): boolean {
  return hasCapability(type, "flash_logging");
}
