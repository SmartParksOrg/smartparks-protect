import { useTranslation } from "react-i18next";
import { useState } from "react";
import { MapPin } from "lucide-react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { Device } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { MiniMap } from "@/components/map/MiniMap";
import { useMutationToast } from "@/hooks/useMutationToast";

/**
 * Where a device is, for hardware that does not move and does not report its place (decision
 * D261): a Bluetooth scanner on a post, a fence monitor. Such a device would otherwise never
 * appear on the map, since it is waiting for a fix that will never come.
 *
 * Setting a place is a statement that the device does not move, so nothing it sends moves it
 * afterwards. It also gives the sightings it makes a place: what a scanner hears was near the
 * scanner, which for an animal carrying a tag and no GNSS is the only position there will be.
 */
export function StaticPositionCard({
  device,
  canEdit,
}: {
  device: Device;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const current = (device.static_position as { coordinates?: number[] } | null)
    ?.coordinates;
  const [latitude, setLatitude] = useState(current ? String(current[1]) : "");
  const [longitude, setLongitude] = useState(current ? String(current[0]) : "");
  const [locating, setLocating] = useState<"idle" | "waiting" | "denied">(
    "idle",
  );
  const lat = Number(latitude);
  const lon = Number(longitude);
  const valid =
    latitude.trim() !== "" &&
    longitude.trim() !== "" &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180;
  const save = useMutationToast({
    mutationFn: (body: { latitude: number | null; longitude: number | null }) =>
      api.put<Device>(`/api/v1/devices/${device.id}/static-position`, { body }),
    invalidate: [queryKeys.device(device.id), ["devices"]],
    success: (d) => (d.static_position ? t("Place saved") : t("Place cleared")),
  });
  const useMyPosition = () => {
    if (!("geolocation" in navigator)) {
      setLocating("denied");
      return;
    }
    setLocating("waiting");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLatitude(p.coords.latitude.toFixed(6));
        setLongitude(p.coords.longitude.toFixed(6));
        setLocating("idle");
      },
      () => setLocating("denied"),
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Place")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          {t(
            "For hardware that does not move and does not report where it is. A place set here is the device's position, nothing it sends moves it, and what it hears over Bluetooth is recorded as having been here.",
          )}
        </p>
        {current && (
          <div className="h-56">
            <MiniMap
              point={[current[0], current[1]]}
              to={`/projects/${device.project_id}/map?device=${device.id}`}
            />
          </div>
        )}
        {canEdit ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                inputMode="decimal"
                value={latitude}
                aria-label={t("Latitude")}
                placeholder={t("Latitude")}
                onChange={(e) => setLatitude(e.target.value)}
              />
              <Input
                inputMode="decimal"
                value={longitude}
                aria-label={t("Longitude")}
                placeholder={t("Longitude")}
                onChange={(e) => setLongitude(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                disabled={!valid || save.isPending}
                onClick={() => save.mutate({ latitude: lat, longitude: lon })}
              >
                {current ? t("Change place") : t("Set place")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={useMyPosition}
                disabled={locating === "waiting"}
              >
                <MapPin className="size-4" />{" "}
                {locating === "waiting" ? t("Locating…") : t("Use my position")}
              </Button>
              {current && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={save.isPending}
                  onClick={() =>
                    save.mutate({ latitude: null, longitude: null })
                  }
                >
                  {t("Clear the place")}
                </Button>
              )}
              {locating === "denied" && (
                <span className="text-xs text-muted-foreground">
                  {t("The browser gave no position.")}
                </span>
              )}
            </div>
          </>
        ) : (
          <p className="text-muted-foreground">
            {current
              ? t("{{lat}}, {{lon}}", {
                  lat: current[1].toFixed(6),
                  lon: current[0].toFixed(6),
                })
              : t("No place set.")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
