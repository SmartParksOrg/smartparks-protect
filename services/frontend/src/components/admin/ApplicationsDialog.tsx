import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link2, Loader2, RefreshCw, Unlink } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type {
  ApplicationStatus,
  ConnectApplicationsResult,
  DataSource,
  DisconnectApplicationsResult,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type RowState = {
  pending: "connect" | "disconnect" | null;
  error: string | null;
};

/** The platform's applications and whether each posts to this source (decision D132): connect
 * or disconnect one at a time, with a spinner on the row while ChirpStack answers, or connect
 * every application that does not post to us yet, one after the other. Only this source's
 * URL entry is ever added or removed; other URLs and every header stay. */
export function ApplicationsDialog({
  source,
  onClose,
}: {
  source: DataSource | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [runningAll, setRunningAll] = useState(false);
  const applications = useQuery({
    queryKey: ["data-sources", source?.id, "applications"],
    queryFn: () =>
      api.get<ApplicationStatus[]>(
        `/api/v1/data-sources/${source?.id}/applications`,
      ),
    enabled: source !== null,
  });
  const setRow = (id: string, patch: Partial<RowState>) =>
    setRows((r) => {
      const current = r[id] ?? { pending: null, error: null };
      return { ...r, [id]: { ...current, ...patch } };
    });

  const connect = async (a: ApplicationStatus) => {
    if (!source) return;
    setRow(a.application_id, { pending: "connect", error: null });
    try {
      const result = await api.post<ConnectApplicationsResult>(
        `/api/v1/data-sources/${source.id}/connect-applications`,
        { body: { application_ids: [a.application_id] } },
      );
      const outcome = result.applications[0];
      if (outcome?.outcome === "failed")
        setRow(a.application_id, {
          pending: null,
          error: outcome.error ?? t("failed"),
        });
      else setRow(a.application_id, { pending: null, error: null });
    } catch (error) {
      setRow(a.application_id, {
        pending: null,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    await applications.refetch();
  };
  const disconnect = async (a: ApplicationStatus) => {
    if (!source) return;
    setRow(a.application_id, { pending: "disconnect", error: null });
    try {
      const result = await api.post<DisconnectApplicationsResult>(
        `/api/v1/data-sources/${source.id}/disconnect-applications`,
        { body: { application_ids: [a.application_id] } },
      );
      const outcome = result.applications[0];
      if (outcome?.outcome === "failed")
        setRow(a.application_id, {
          pending: null,
          error: outcome.error ?? t("failed"),
        });
      else setRow(a.application_id, { pending: null, error: null });
    } catch (error) {
      setRow(a.application_id, {
        pending: null,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    await applications.refetch();
  };
  const connectAll = async () => {
    const todo = (applications.data ?? []).filter(
      (a) => a.state !== "connected",
    );
    setRunningAll(true);
    for (const a of todo) await connect(a);
    setRunningAll(false);
    toast.success(
      t("{{count}} applications connected", { count: todo.length }),
    );
  };

  const list = applications.data ?? [];
  const notConnected = list.filter((a) => a.state !== "connected").length;
  const stateText = (a: ApplicationStatus) =>
    a.state === "connected"
      ? t("posts to this source")
      : a.state === "other"
        ? t("posts elsewhere only")
        : t("no HTTP integration");
  const keptText = (a: ApplicationStatus) => {
    const others = (a.urls ?? []).filter(
      (u) => !u.includes("/api/v1/ingest/http/"),
    ).length;
    const parts = [
      others > 0
        ? t("{{count}} other URL", { count: others })
        : t("no other URL"),
    ];
    if ((a.headers ?? []).length > 0)
      parts.push(t("{{count}} header", { count: (a.headers ?? []).length }));
    return parts.join(", ");
  };

  return (
    <Dialog open={source !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t("Applications of {{name}}", { name: source?.name })}
          </DialogTitle>
          <DialogDescription>
            {t(
              "Every application of the tenant and whether its HTTP integration posts to this source. Connect adds this source's URL to the application's list, Disconnect removes it; other URLs and headers are never touched.",
            )}
          </DialogDescription>
        </DialogHeader>
        {applications.isError && (
          <Callout kind="error">{applications.error.message}</Callout>
        )}
        {applications.isPending && source && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />{" "}
            {t("Asking the platform…")}
          </div>
        )}
        {applications.data && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1">{t("Application")}</th>
                <th>{t("State")}</th>
                <th>{t("Kept")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((a) => {
                const row = rows[a.application_id] ?? {
                  pending: null,
                  error: null,
                };
                return (
                  <tr key={a.application_id} className="border-t align-top">
                    <td className="py-1.5 font-medium">{a.name}</td>
                    <td className="py-1.5">
                      {row.pending === "connect" ? (
                        <span className="inline-flex items-center gap-1 text-muted-foreground">
                          <Loader2 className="size-4 animate-spin" />{" "}
                          {t("connecting…")}
                        </span>
                      ) : row.pending === "disconnect" ? (
                        <span className="inline-flex items-center gap-1 text-muted-foreground">
                          <Loader2 className="size-4 animate-spin" />{" "}
                          {t("disconnecting…")}
                        </span>
                      ) : (
                        stateText(a)
                      )}
                      {row.error && (
                        <div className="text-xs text-destructive">
                          {row.error}
                        </div>
                      )}
                    </td>
                    <td className="py-1.5 text-xs text-muted-foreground">
                      {keptText(a)}
                    </td>
                    <td className="py-1 text-right">
                      {a.state === "connected" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={row.pending !== null || runningAll}
                          onClick={() => void disconnect(a)}
                        >
                          <Unlink className="size-4" /> {t("Disconnect")}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          disabled={row.pending !== null || runningAll}
                          onClick={() => void connect(a)}
                        >
                          <Link2 className="size-4" /> {t("Connect")}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {applications.data && list.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t("The tenant has no application.")}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            disabled={applications.isFetching}
            onClick={() => void applications.refetch()}
          >
            <RefreshCw
              className={`size-4 ${applications.isFetching ? "animate-spin" : ""}`}
            />{" "}
            {t("Refresh")}
          </Button>
          {notConnected > 0 && (
            <Button
              variant="outline"
              disabled={runningAll}
              onClick={() => void connectAll()}
            >
              {runningAll ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Link2 className="size-4" />
              )}{" "}
              {t("Connect the other {{count}}", { count: notConnected })}
            </Button>
          )}
          <Button onClick={onClose}>{t("Done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
