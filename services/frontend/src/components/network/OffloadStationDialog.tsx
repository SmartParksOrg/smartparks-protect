import { useQuery } from "@tanstack/react-query";
import { LocateFixed } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  OffloadStationSetup,
  OffloadStationSetupResult,
  Page as PageType,
} from "@/api/types";
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

const coordinatesOf = (device: Device | undefined): [number, number] | null => {
  const c = (device?.static_position as { coordinates?: number[] } | null)
    ?.coordinates;
  return c && c.length >= 2 ? [c[0], c[1]] : null;
};

/**
 * A device of the project becomes an offload station in one dialog (Tim, 2026-10-16), or a
 * station that misses a piece is completed from its row on the Offload page: pick the
 * RangerEdge, give it a place (a click on the map, the coordinates, or the browser's position
 * while standing at it) and it gets an Offload station entity (the entity it tracks today is
 * kept), the place, and its row among the gateways of the offload station source, so the page
 * lists it before its first card. The server does the three in one call and never undoes one.
 */
export function OffloadStationDialog({
  projectId,
  open,
  onOpenChange,
  deviceId,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The station to complete; nothing for a new one. */
  deviceId: string | null;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("Make an offload station")}</DialogTitle>
          <DialogDescription>
            {t(
              "A RangerEdge with an SD card that trackers offload their flash logs to. It becomes an Offload station entity with its place and a gateway of the offload station source; its card is uploaded on its device page afterwards.",
            )}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <SetupForm
            projectId={projectId}
            initialDeviceId={deviceId}
            onDone={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Mounted while the dialog is open, so every opening starts afresh. */
function SetupForm({
  projectId,
  initialDeviceId,
  onDone,
}: {
  projectId: string;
  initialDeviceId: string | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const devices = useQuery({
    queryKey: queryKeys.devices({ projectId, limit: 500 }),
    queryFn: () =>
      api.get<PageType<Device>>("/api/v1/devices", {
        query: { project_id: projectId, limit: 500 },
      }),
  });
  const [deviceId, setDeviceId] = useState(initialDeviceId ?? "");
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  // the place as typed, clicked or located here; until then the device's own place, if any
  const [place, setPlace] = useState<{ lat: string; lon: string } | null>(null);
  const [locating, setLocating] = useState<"idle" | "waiting" | "denied">(
    "idle",
  );
  const [attempted, setAttempted] = useState(false);
  const chosen = devices.data?.items.find((d) => d.id === deviceId);
  const own = coordinatesOf(chosen);
  const latitude = place ? place.lat : own ? String(own[1]) : "";
  const longitude = place ? place.lon : own ? String(own[0]) : "";
  const setLatitude = (lat: string) => setPlace({ lat, lon: longitude });
  const setLongitude = (lon: string) => setPlace({ lat: latitude, lon });
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const items = devices.data?.items ?? [];
    if (!needle) return items;
    return items.filter(
      (d) =>
        d.name.toLowerCase().includes(needle) ||
        (d.serial_number ?? "").toLowerCase().includes(needle),
    );
  }, [devices.data, q]);
  const lat = Number(latitude);
  const lon = Number(longitude);
  const placeEmpty = latitude.trim() === "" && longitude.trim() === "";
  const placeValid =
    !placeEmpty &&
    latitude.trim() !== "" &&
    longitude.trim() !== "" &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180;
  const missing = !deviceId
    ? "device"
    : !placeEmpty && !placeValid
      ? "place"
      : null;
  const useMyPosition = () => {
    if (!("geolocation" in navigator)) {
      setLocating("denied");
      return;
    }
    setLocating("waiting");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setPlace({
          lat: p.coords.latitude.toFixed(6),
          lon: p.coords.longitude.toFixed(6),
        });
        setLocating("idle");
      },
      () => setLocating("denied"),
      { enableHighAccuracy: true, timeout: 15_000 },
    );
  };
  const setUp = useMutationToast({
    mutationFn: () => {
      const body: OffloadStationSetup = { device_id: deviceId };
      if (!chosen?.entity_id && name.trim()) body.entity_name = name.trim();
      if (placeValid) {
        body.latitude = lat;
        body.longitude = lon;
      }
      return api.post<OffloadStationSetupResult>(
        `/api/v1/projects/${projectId}/offload/stations`,
        { body },
      );
    },
    invalidate: [
      queryKeys.projectOffload(projectId),
      queryKeys.devices({}),
      queryKeys.device(deviceId),
      queryKeys.entities(projectId),
      queryKeys.currentState(projectId),
      ["projects", projectId, "gateways"],
    ],
    success: (r) =>
      r.entity_created
        ? t("{{device}} is an offload station now, as the entity {{entity}}", {
            device: r.device_name,
            entity: r.entity_name,
          })
        : t("{{device}} is set up as an offload station; it stays on {{entity}}", {
            device: r.device_name,
            entity: r.entity_name,
          }),
    onSuccess: onDone,
  });
  const point: [number, number] | undefined = placeValid ? [lon, lat] : undefined;
  return (
    <>
      <div className="min-w-0 space-y-4">
        <Field
          label={t("Device")}
          htmlFor="station-device-search"
          hint={t(
            "A device of this project whose serial number is its DevEUI: the station names the card's files after it.",
          )}
          error={attempted && missing === "device" ? t("Pick a device from the list") : undefined}
        >
          <Input
            id="station-device-search"
            placeholder={t("Search by name or serial")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </Field>
        <div
          className="max-h-48 overflow-y-auto rounded-md border"
          role="listbox"
          aria-label={t("Devices")}
        >
          {devices.isPending && (
            <div className="p-3 text-sm text-muted-foreground">{t("Loading devices…")}</div>
          )}
          {devices.data && shown.length === 0 && (
            <div className="p-3 text-sm text-muted-foreground">
              {q ? t("No device matches.") : t("No devices in this project yet.")}
            </div>
          )}
          {shown.map((d) => (
            <button
              key={d.id}
              type="button"
              role="option"
              aria-selected={d.id === deviceId}
              className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted ${d.id === deviceId ? "bg-muted" : ""}`}
              onClick={() => {
                setDeviceId(d.id);
                setPlace(null); // the new device's own place, if any
              }}
            >
              <span className="min-w-0 flex-1 truncate font-medium">{d.name}</span>
              {d.serial_number && (
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {d.serial_number}
                </span>
              )}
              <span className="shrink-0 text-xs text-muted-foreground">
                {d.entity_name
                  ? t("tracks {{entity}}", { entity: d.entity_name })
                  : t("no entity")}
              </span>
            </button>
          ))}
        </div>
        {chosen && !chosen.serial_number && (
          <Callout kind="warning">
            {t(
              "{{name}} has no serial number. Set its DevEUI as the serial on its device page first; without it the station's files cannot be matched to it.",
              { name: chosen.name },
            )}
          </Callout>
        )}
        {chosen &&
          (chosen.entity_id ? (
            <Callout kind="info">
              {t(
                "{{device}} tracks {{entity}} today; that entity stays the station's. Release it on the device page first if the station should be an entity of its own.",
                { device: chosen.name, entity: chosen.entity_name ?? "" },
              )}
            </Callout>
          ) : (
            <Field
              label={t("Entity name")}
              htmlFor="station-entity-name"
              hint={t(
                "A new entity of the type Offload station, so the station has a name on the map and in the lists. The device's name when left empty.",
              )}
            >
              <Input
                id="station-entity-name"
                placeholder={chosen.name}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
          ))}
        <Field
          label={t("Place")}
          htmlFor="station-lat"
          hint={t(
            "A station does not move, so its place is set by hand: click the map, type the coordinates, or take your position while standing at it. Leave it empty to set it later on the device page.",
          )}
          error={
            attempted && missing === "place"
              ? t("Give both coordinates, or neither")
              : undefined
          }
        >
          <div className="h-48">
            <MiniMap
              point={point}
              fallback={point ?? own ?? undefined}
              to=""
              label={t("Click to place")}
              onPick={([pickedLon, pickedLat]) => {
                setPlace({ lat: pickedLat.toFixed(6), lon: pickedLon.toFixed(6) });
              }}
            />
          </div>
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input
            id="station-lat"
            inputMode="decimal"
            aria-label={t("Latitude")}
            placeholder={t("Latitude")}
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
          />
          <Input
            id="station-lon"
            inputMode="decimal"
            aria-label={t("Longitude")}
            placeholder={t("Longitude")}
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
          />
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
        {setUp.isError && <Callout kind="error">{setUp.error.message}</Callout>}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          {t("Cancel")}
        </Button>
        <Button
          type="button"
          disabled={setUp.isPending}
          onClick={() => (missing === null ? setUp.mutate() : setAttempted(true))}
        >
          {setUp.isPending ? t("Setting up…") : t("Make it a station")}
        </Button>
      </DialogFooter>
    </>
  );
}
