import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  Device,
  DeviceType,
  OffloadStationSetupResult,
  OffloadUpload,
  Page as PageType,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
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

/**
 * A card from a station the project does not have (decision D343, Tim, 2026-10-19: a clear
 * process when an SD card file names an unregistered station). The upload kept nothing of
 * such files and answered with the station's EUI; here the person gives the station its name
 * from the label (the EUI stands in), it is made with the EUI as serial and set up as a station
 * in one go, and the same files go up again, this time to it. Its place follows on its page.
 */
export function UnknownStationDialog({
  projectId,
  euis,
  files,
  onOpenChange,
  onUploaded,
}: {
  projectId: string;
  /** The EUIs the upload named; nothing closes the dialog. */
  euis: string[] | null;
  /** The files the person picked, to go up again once the stations exist. */
  files: File[];
  onOpenChange: (open: boolean) => void;
  onUploaded: (results: OffloadUpload[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={euis !== null && euis.length > 0} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {t("The card is from a station this project does not have", {
              count: euis?.length ?? 0,
            })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "The files are named after a station's DevEUI and were not kept. Give the station its name from the label (SP…) when you know it, or leave the DevEUI; it is made with the DevEUI as serial, set up as an offload station, and the files go up to it. Its place is set on its page afterwards.",
            )}
          </DialogDescription>
        </DialogHeader>
        {euis && euis.length > 0 && (
          <StationForm
            projectId={projectId}
            euis={euis}
            files={files}
            onDone={() => onOpenChange(false)}
            onUploaded={onUploaded}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function StationForm({
  projectId,
  euis,
  files,
  onDone,
  onUploaded,
}: {
  projectId: string;
  euis: string[];
  files: File[];
  onDone: () => void;
  onUploaded: (results: OffloadUpload[]) => void;
}) {
  const { t } = useTranslation();
  const [names, setNames] = useState<Record<string, string>>(
    Object.fromEntries(euis.map((eui) => [eui, eui])),
  );
  const types = useQuery({
    queryKey: queryKeys.deviceTypes,
    queryFn: () =>
      api.get<PageType<DeviceType>>("/api/v1/device-types", {
        query: { limit: 500 },
      }),
  });
  // a station is a RangerEdge, an OpenCollar type; the one called Edge when there is one
  const openCollar = (types.data?.items ?? []).filter(
    (x) => x.driver_key === "opencollar",
  );
  const stationType =
    openCollar.find((x) => /edge/i.test(x.label)) ?? openCollar[0] ?? null;
  const valid = euis.every((eui) => names[eui]?.trim()) && stationType !== null;
  const make = useMutationToast({
    mutationFn: async () => {
      if (!stationType)
        throw new Error(t("This server has no OpenCollar device type yet"));
      const made: string[] = [];
      for (const eui of euis) {
        const device = await api.post<Device>(
          `/api/v1/projects/${projectId}/devices`,
          {
            body: {
              device_type_id: stationType.id,
              name: names[eui].trim(),
              serial_number: eui,
            },
          },
        );
        const setup = await api.post<OffloadStationSetupResult>(
          `/api/v1/projects/${projectId}/offload/stations`,
          {
            body: {
              device_id: device.id,
              entity_name: t("Station {{name}}", { name: device.name }),
            },
          },
        );
        made.push(setup.device_name);
      }
      // the same files again: they find their stations now; files kept the first time are
      // skipped as uploaded before, which is right
      const results: OffloadUpload[] = [];
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        results.push(
          await api.post<OffloadUpload>(
            `/api/v1/projects/${projectId}/offload-files`,
            { body },
          ),
        );
      }
      return { made, results };
    },
    invalidate: [
      queryKeys.projectOffload(projectId),
      ["projects", projectId, "log-files"],
    ],
    success: (r) =>
      t(
        "{{stations}} set up as offload stations; {{files}} files uploaded, decoding",
        {
          stations: r.made.join(", "),
          files: r.results.reduce((n, x) => n + x.files.length, 0),
        },
      ),
    onSuccess: (r) => {
      onUploaded(r.results);
      onDone();
    },
  });
  return (
    <div className="space-y-4">
      {euis.map((eui) => (
        <Field
          key={eui}
          label={t("Station {{eui}}", { eui })}
          htmlFor={`station-name-${eui}`}
          hint={t(
            "The name on its label (SP…); the DevEUI {{eui}} becomes its serial number.",
            {
              eui,
            },
          )}
        >
          <Input
            id={`station-name-${eui}`}
            value={names[eui] ?? ""}
            onChange={(e) => setNames({ ...names, [eui]: e.target.value })}
            autoComplete="off"
          />
        </Field>
      ))}
      {types.data && !stationType && (
        <Callout kind="warning">
          {t(
            "This server has no OpenCollar device type yet; a server admin adds one under Server admin, Device types.",
          )}
        </Callout>
      )}
      {make.isError && <Callout kind="error">{make.error.message}</Callout>}
      <DialogFooter className="gap-2">
        <Button type="button" variant="outline" onClick={onDone}>
          {t("Not now")}
        </Button>
        <Button
          type="button"
          disabled={!valid || make.isPending}
          onClick={() => make.mutate()}
        >
          {make.isPending
            ? t("Setting up…")
            : t("Make the station and upload", { count: euis.length })}
        </Button>
      </DialogFooter>
    </div>
  );
}
