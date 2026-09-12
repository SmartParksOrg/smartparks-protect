import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { dotLevel, type StatusSummary } from "@/lib/health";
import { useAuthStore } from "@/stores/auth";

const COLOUR = {
  ok: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-red-500",
  unknown: "bg-muted-foreground/40",
};

/**
 * The small system health dot (decision D181): green while everything reports, amber when the
 * server's summary says a worker or a system alert lingers, red only after two
 * polls in a row without any answer. A click tells why, and server admins get the way to System health.
 */
export function HealthDot({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  const admin = useAuthStore((s) => Boolean(s.user?.is_superuser));
  const status = useQuery({
    queryKey: ["system", "status"],
    queryFn: () => api.get<StatusSummary>("/api/v1/system/status"),
    refetchInterval: 60_000,
    retry: false,
  });
  // failureCount counts the failed polls since the last answer; two in a row means red
  const level = dotLevel(status.data, status.failureCount);
  const label =
    level === "ok"
      ? t("All systems working")
      : level === "degraded"
        ? t("Something needs a look")
        : level === "down"
          ? t("No answer from the server")
          : t("Checking the system");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={`flex size-4 items-center justify-center rounded-full ${className}`}
          aria-label={t("System health: {{state}}", { state: label })}
          title={label}
        >
          <span className={`block size-2.5 rounded-full ${COLOUR[level]}`} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 text-sm">
        <div className="flex items-center gap-2 font-medium">
          <span className={`block size-2.5 rounded-full ${COLOUR[level]}`} />
          {label}
        </div>
        {level === "degraded" && status.data && (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-muted-foreground">
            {status.data.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        {level === "down" && (
          <p className="mt-2 text-muted-foreground">
            {t("No answer from the server for two polls in a row. The page keeps trying every minute.")}
          </p>
        )}
        {level === "ok" && (
          <p className="mt-2 text-muted-foreground">
            {t("Every worker reports and no system alert is open.")}
          </p>
        )}
        {admin && (
          <Link className="mt-2 block underline" to="/admin/health">
            {t("System health")}
          </Link>
        )}
      </PopoverContent>
    </Popover>
  );
}
