import { type QueryKey, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type {
  IntegrationSubject,
  IntegrationSubjectOptions,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

/** The longest history one request sends, as the API allows it. */
const MAX_HISTORY_DAYS = 400;

const day = (d: Date) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);

/** Integrate one entity with a target that keeps a register of its own (decisions D412,
 * D413 and D416): the species picked from the target's own list with Protect's proposal
 * chosen already, the sensor id the entity will be known by, what the target has for that
 * sensor (on this animal, on another one, or nothing), and whether its history goes first.
 * With history the old data is sent oldest first and the registration follows the last of
 * it (decision D409), since a target may react to old readings of an animal it knows. */
export function IntegrateEntityDialog({
  projectId,
  entityId,
  integrationId,
  target,
  open,
  onOpenChange,
}: {
  projectId: string;
  entityId: string;
  integrationId: string;
  /** The connector's name, as the page shows it. */
  target: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const path = `/api/v1/projects/${projectId}/integrations/${integrationId}/subjects/${entityId}`;
  const options = useQuery({
    queryKey: queryKeys.integrationSubjectOptions(
      projectId,
      integrationId,
      entityId,
    ),
    queryFn: () => api.get<IntegrationSubjectOptions>(`${path}/options`),
    enabled: open,
    retry: false,
    // asked again at every opening: what the target has may have changed
    gcTime: 0,
  });
  const data = options.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {data
              ? t("Integrate {{name}} with {{target}}", {
                  name: data.entity_name,
                  target,
                })
              : t("Integrate with {{target}}", { target })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "Its data is forwarded to {{target}} from now on, and it is registered there as an animal with its sensor.",
              { target },
            )}
          </DialogDescription>
        </DialogHeader>
        {options.isPending ? (
          <p className="text-sm text-muted-foreground">
            {t("Asking {{target}}…", { target })}
          </p>
        ) : options.error ? (
          <Callout kind="error">{options.error.message}</Callout>
        ) : data ? (
          // the form starts from what the target answered, so it mounts with the answer
          <IntegrateForm
            data={data}
            path={path}
            target={target}
            invalidate={[
              queryKeys.entityIntegrations(projectId, entityId),
              queryKeys.integrationSubjects(projectId, integrationId),
            ]}
            onDone={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function IntegrateForm({
  data,
  path,
  target,
  invalidate,
  onDone,
}: {
  data: IntegrationSubjectOptions;
  path: string;
  target: string;
  invalidate: QueryKey[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  // as far back as one request reaches, fixed when the dialog opens
  const [earliest] = useState(
    () => new Date(Date.now() - MAX_HISTORY_DAYS * 86_400_000),
  );
  const [today] = useState(() => day(new Date()));
  // what was chosen before, else Protect's proposal
  const [species, setSpecies] = useState(
    data.subject?.species_id ?? data.proposed_species_id ?? "",
  );
  // no history for a sensor the target knows already: its old data would move the animal
  const [history, setHistory] = useState(
    !data.target.registered && Boolean(data.device_name),
  );
  // from the day the device came onto the entity
  const [from, setFrom] = useState(() => {
    const since = data.assigned_from ? new Date(data.assigned_from) : earliest;
    return day(since > earliest ? since : earliest);
  });
  const [error, setError] = useState<string | null>(null);
  const chosen = data.species.find((s) => s.id === species);
  const save = useMutationToast({
    mutationFn: () =>
      api.put<IntegrationSubject>(path, {
        body: {
          species_id: species,
          species_name: chosen?.name ?? null,
          history_from: history
            ? new Date(`${from}T00:00:00`).toISOString()
            : null,
        },
      }),
    invalidate,
    success: (row) =>
      row.state === "registered"
        ? t("Integrated with {{target}}", { target })
        : row.state === "failed"
          ? t("{{target}} refused the registration", { target })
          : t("The history is on its way; the registration follows it"),
    onSuccess: onDone,
    onError: (e) => setError(e.message),
  });
  return (
    <>
      <div className="space-y-4">
        {data.blocked && <Callout kind="warning">{data.blocked}</Callout>}
        {data.target.registered && (
          <Callout kind="info">
            {t(
              "{{target}} has this sensor on this entity's animal since {{time}}. Nothing new is sent; the data is forwarded.",
              { target, time: formatTime(data.target.since) },
            )}
          </Callout>
        )}
        {data.target.elsewhere && (
          <Callout kind="warning">
            {t(
              "{{target}} has this sensor on {{name}} since {{time}}. Integrating puts it on this entity's animal from {{from}}, and {{target}} ends it on {{name}} then. The history is sent after that.",
              {
                target,
                name: data.target.elsewhere,
                time: formatTime(data.target.since),
                from: formatTime(data.assigned_from),
              },
            )}
          </Callout>
        )}
        {!data.device_name && (
          <Callout kind="info">
            {t(
              "No device is on this entity. Its animal is made now; the first device assigned to it waits for your confirmation on the entity's page.",
            )}
          </Callout>
        )}
        <Field
          label={t("Species on {{target}}", { target })}
          htmlFor="subject-species"
          hint={
            data.proposed_species_id
              ? t(
                  "Proposed from the entity's type. Change it when it is wrong.",
                )
              : t("No match was found for the entity's type. Pick the species.")
          }
        >
          <Select value={species} onValueChange={setSpecies}>
            <SelectTrigger id="subject-species">
              <SelectValue placeholder={t("Choose a species")} />
            </SelectTrigger>
            <SelectContent>
              {data.species.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.common_name ? `${s.common_name} (${s.name})` : s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <dl className="grid grid-cols-[fit-content(45%)_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("Device")}</dt>
          <dd>{data.device_name ?? t("none")}</dd>
          <dt className="text-muted-foreground">{t("Sensor id")}</dt>
          <dd className="font-mono text-xs break-all">
            {data.sensor_id ?? t("none")}
          </dd>
        </dl>
        <label className="flex items-start gap-2 text-sm">
          <Switch
            className="mt-0.5"
            checked={history}
            onCheckedChange={setHistory}
          />
          <span>
            {t("Send its history first")}
            <span className="block text-xs text-muted-foreground">
              {t(
                "The old data goes first, oldest first, and the registration follows the last of it. Without it the entity is registered at once and only new data is sent.",
              )}
            </span>
          </span>
        </label>
        {history && (
          <Field
            label={t("History from")}
            htmlFor="subject-from"
            hint={t("At most {{count}} days back", { count: MAX_HISTORY_DAYS })}
          >
            <Input
              id="subject-from"
              type="date"
              min={day(earliest)}
              max={today}
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </Field>
        )}
        {error && <Callout kind="error">{error}</Callout>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onDone}>
          {t("Cancel")}
        </Button>
        <Button
          disabled={
            Boolean(data.blocked) ||
            !species ||
            (history && !from) ||
            save.isPending
          }
          onClick={() => save.mutate()}
        >
          {save.isPending ? t("Integrating…") : t("Integrate")}
        </Button>
      </DialogFooter>
    </>
  );
}
