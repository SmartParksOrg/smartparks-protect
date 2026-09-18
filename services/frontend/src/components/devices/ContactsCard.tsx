import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { DeviceContacts } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatAgo, formatTime } from "@/lib/format";
import { useNow } from "@/hooks/useNow";

const HOURS = 168;

/**
 * What this device saw over the last week (phase 30, decisions D252 to D254).
 *
 * It exists to be read against reality before an analysis is built on it, so it shows what the
 * device reported and what was made of it, and nothing more. The scanning line above the list is
 * the important part: an empty list means "it met nobody" only if the device was looking, and
 * Bluetooth scanning is off until somebody turns it on.
 */
export function ContactsCard({
  deviceId,
  canScan = true,
}: {
  deviceId: string;
  /** A tag scans for nothing, so its card is only about what heard it. */
  canScan?: boolean;
}) {
  const { t } = useTranslation();
  const now = useNow();
  const contacts = useQuery({
    queryKey: ["devices", deviceId, "contacts", HOURS],
    queryFn: () =>
      api.get<DeviceContacts>(`/api/v1/devices/${deviceId}/contacts`, {
        query: { hours: HOURS },
      }),
  });
  const data = contacts.data;
  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>{t("Bluetooth contacts")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {contacts.isPending && (
          <p className="text-muted-foreground">{t("Loading…")}</p>
        )}
        {data && canScan && !data.scanning.known && (
          <Callout kind="info">
            {t(
              "Protect does not know whether this device scans for Bluetooth neighbours. Read its settings to find out; scanning is off until somebody turns it on.",
            )}
          </Callout>
        )}
        {data && canScan && data.scanning.known && !data.scanning.enabled && (
          <Callout kind="warning">
            {t(
              "Bluetooth scanning is off on this device, so it reports no neighbours. An empty list here says nothing about what it met.",
            )}
          </Callout>
        )}
        {data && canScan && data.scanning.enabled && (
          <p className="text-muted-foreground">
            {data.scanning.filter_label
              ? t("Scanning for {{what}}, last scan {{ago}}.", {
                  what: data.scanning.filter_label,
                  ago: formatAgo(data.last_scan_at, now),
                })
              : t("Scanning, last scan {{ago}}.", {
                  ago: formatAgo(data.last_scan_at, now),
                })}
          </p>
        )}
        {data &&
          canScan &&
          data.counterparts.length === 0 &&
          data.scanning.enabled && (
            <p className="text-muted-foreground">
              {t("No neighbour seen in the last {{days}} days.", {
                days: Math.round(HOURS / 24),
              })}
            </p>
          )}
        {data && data.counterparts.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1">{t("Neighbour")}</th>
                  <th>{t("Contacts")}</th>
                  <th>{t("Sightings")}</th>
                  <th>{t("Strongest")}</th>
                  <th>{t("Last")}</th>
                </tr>
              </thead>
              <tbody>
                {data.counterparts.map((c) => (
                  <tr key={`${c.address}-${c.resolution}`} className="border-t">
                    <td className="py-1">
                      {c.resolution === "resolved" ? (
                        <span>
                          {c.device_name}
                          {c.entity_name && (
                            <span className="text-muted-foreground">
                              {" "}
                              · {c.entity_name}
                            </span>
                          )}
                        </span>
                      ) : c.resolution === "ambiguous" ? (
                        <span
                          className="text-brand-sand"
                          title={t(
                            "More than one device ends with these octets, so this contact is not counted for either",
                          )}
                        >
                          {t("could be {{names}}", {
                            names: (c.candidate_names ?? []).join(", "),
                          })}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          {t("unknown")}
                        </span>
                      )}
                      <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                        {c.address}
                      </span>
                    </td>
                    <td>{c.contacts}</td>
                    <td>{c.sightings}</td>
                    <td>
                      {c.best_rssi_dbm == null
                        ? ""
                        : t("{{value}} dBm", { value: c.best_rssi_dbm })}
                    </td>
                    <td title={formatTime(c.last_at)}>
                      {formatAgo(c.last_at, now)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (data.heard_by ?? []).length > 0 && (
          <div className="space-y-1">
            <p className="font-medium">{t("Heard by")}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="py-1">{t("Device")}</th>
                    <th>{t("Contacts")}</th>
                    <th>{t("Strongest")}</th>
                    <th>{t("Last")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.heard_by ?? []).map((r) => (
                    <tr key={r.device_id ?? r.address} className="border-t">
                      <td className="py-1">
                        {r.device_name}
                        {r.entity_name && (
                          <span className="text-muted-foreground">
                            {" "}
                            · {r.entity_name}
                          </span>
                        )}
                      </td>
                      <td>{r.contacts}</td>
                      <td>
                        {r.best_rssi_dbm == null
                          ? ""
                          : t("{{value}} dBm", { value: r.best_rssi_dbm })}
                      </td>
                      <td title={formatTime(r.last_at)}>
                        {formatAgo(r.last_at, now)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {data && (data.unknown > 0 || data.ambiguous > 0) && (
          <p className="text-muted-foreground">
            {t(
              "A neighbour is unknown when no device of this project carries that address; a device's own address becomes known when it is asked for it under Control. The signal is not a distance: it says how strongly the device heard, which the surroundings change as much as the range does.",
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
