import { LocateFixed } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { Gateway } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { MiniMap } from "@/components/map/MiniMap";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationToast } from "@/hooks/useMutationToast";

const coordinatesOf = (gateway: Gateway | null): [number, number] | null => {
  const c = (gateway?.geometry as { coordinates?: number[] } | null)
    ?.coordinates;
  return c && c.length >= 2 ? [c[0], c[1]] : null;
};

/** A gateway placed by hand (decision D239): a Gateway Mesh relay or a gateway on a network
 * without a gateway API gives no location, so the map cannot show it. Type the coordinates,
 * click the map, or take the browser's position when standing at the gateway. A location set
 * this way is kept over the platform's; "Clear" gives it back to the platform. */
export function GatewayLocationDialog({
  projectId,
  gateway,
  onClose,
  fallback,
}: {
  projectId: string;
  gateway: Gateway | null;
  onClose: () => void;
  /** Where the map looks when the gateway has no location yet, [lon, lat]. */
  fallback?: [number, number] | null;
}) {
  const { t } = useTranslation();
  const current = coordinatesOf(gateway);
  const [latitude, setLatitude] = useState(current ? String(current[1]) : "");
  const [longitude, setLongitude] = useState(current ? String(current[0]) : "");
  const [altitude, setAltitude] = useState(
    gateway?.altitude_m != null ? String(gateway.altitude_m) : "",
  );
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
    mutationFn: (body: {
      latitude: number | null;
      longitude: number | null;
      altitude_m?: number | null;
    }) =>
      api.patch<Gateway>(
        `/api/v1/projects/${projectId}/gateways/${gateway?.id}/location`,
        { body },
      ),
    invalidate: [["projects", projectId, "gateways"]],
    success: t("Gateway location saved"),
    onSuccess: onClose,
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
        if (p.coords.altitude != null)
          setAltitude(String(Math.round(p.coords.altitude)));
        setLocating("idle");
      },
      () => setLocating("denied"),
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  };
  const point: [number, number] | undefined = valid ? [lon, lat] : undefined;
  return (
    <Dialog open={gateway !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t("Location of {{name}}", { name: gateway?.display_name ?? "" })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "A gateway the network gave no location for cannot be placed on the map. Type the coordinates, click the map, or take your position while standing at it. A location set here is kept over the platform's.",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="h-56">
            <MiniMap
              point={point}
              fallback={point ?? fallback ?? undefined}
              to=""
              label={t("Click to place")}
              onPick={([pickedLon, pickedLat]) => {
                setLatitude(String(pickedLat));
                setLongitude(String(pickedLon));
              }}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={t("Latitude")} htmlFor="gw-lat">
              <Input
                id="gw-lat"
                inputMode="decimal"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
              />
            </Field>
            <Field label={t("Longitude")} htmlFor="gw-lon">
              <Input
                id="gw-lon"
                inputMode="decimal"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
              />
            </Field>
            <Field label={t("Altitude (m)")} htmlFor="gw-alt">
              <Input
                id="gw-alt"
                inputMode="decimal"
                value={altitude}
                onChange={(e) => setAltitude(e.target.value)}
              />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={useMyPosition}
              disabled={locating === "waiting"}
            >
              <LocateFixed className="size-4" />{" "}
              {locating === "waiting" ? t("Locating…") : t("Use my position")}
            </Button>
            {locating === "denied" && (
              <span className="text-xs text-muted-foreground">
                {t("The browser gave no position.")}
              </span>
            )}
          </div>
          {gateway?.location_source &&
            gateway.location_source !== "admin" &&
            valid && (
              <Callout kind="info">
                {t(
                  "The platform reported a location for this gateway; the one you save replaces it on the map until you clear it.",
                )}
              </Callout>
            )}
        </div>
        <DialogFooter className="gap-2 sm:justify-between">
          <div>
            {gateway?.location_source === "admin" && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={save.isPending}
                onClick={() => save.mutate({ latitude: null, longitude: null })}
              >
                {t("Clear the set location")}
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t("Cancel")}
            </Button>
            <Button
              type="button"
              disabled={!valid || save.isPending}
              onClick={() =>
                save.mutate({
                  latitude: lat,
                  longitude: lon,
                  altitude_m: altitude.trim() === "" ? null : Number(altitude),
                })
              }
            >
              {t("Save location")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
