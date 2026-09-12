import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { X } from "lucide-react";

import { api } from "@/api/client";
import type { Alert } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Icon } from "@/components/icons/Icon";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { type FeedItem, isUnread } from "@/lib/feed";
import { formatAgo, formatTime } from "@/lib/format";
import { eventIcon } from "@/lib/rules";

/**
 * The live map's feed (decisions D177 to D179): the project's newest events with their alert
 * state, unread ones marked, a row flies to the event and opens its detail, an open alert
 * carries Acknowledge for people with the alerts permission.
 */
export function FeedPanel({
  projectId,
  items,
  seenUpTo,
  loading,
  canWriteAlerts,
  entityName,
  onSelect,
  onClose,
}: {
  projectId: string;
  items: FeedItem[];
  seenUpTo: string | null;
  loading: boolean;
  canWriteAlerts: boolean;
  entityName: (id: string | null | undefined) => string | null;
  onSelect: (item: FeedItem) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const acknowledge = useMutationToast({
    mutationFn: (item: FeedItem) =>
      api.post<Alert>(
        `/api/v1/projects/${projectId}/alerts/${item.alert_id}/acknowledge`,
        { body: { note: null } },
      ),
    success: t("Alert acknowledged"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["events", projectId] });
      void client.invalidateQueries({ queryKey: ["alerts", projectId] });
    },
  });
  return (
    <aside
      className="flex min-h-0 flex-1 flex-col rounded-lg border bg-card text-sm shadow-lg"
      aria-label={t("Feed")}
    >
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <span className="font-semibold">{t("Feed")}</span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={t("Close")}
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {items.length === 0 && (
          <li className="px-3 py-6 text-center text-muted-foreground">
            {loading ? t("Loading…") : t("Nothing happened yet.")}
          </li>
        )}
        {items.map((item) => {
          const unread = isUnread(item, seenUpTo);
          const entity = entityName(item.entity_id);
          return (
            <li
              key={item.id}
              className={`border-b last:border-b-0 ${unread ? "border-l-2 border-l-primary bg-primary/5" : ""}`}
            >
              <button
                type="button"
                className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-muted/60"
                onClick={() => onSelect(item)}
              >
                <Icon
                  iconKey={eventIcon(item.event_type)}
                  className="mt-0.5 size-4 shrink-0 text-primary"
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={`block truncate ${unread ? "font-semibold" : ""}`}
                  >
                    {item.title}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <StatusBadge value={item.severity} className="text-[10px]" />
                    {item.alert_status && (
                      <StatusBadge
                        value={item.alert_status}
                        className="text-[10px]"
                      />
                    )}
                    {entity && <span className="truncate">{entity}</span>}
                    <span title={formatTime(item.time)}>{formatAgo(item.time)}</span>
                  </span>
                </span>
                {canWriteAlerts && item.alert_id && item.alert_status === "open" && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 px-2 text-xs"
                    disabled={acknowledge.isPending}
                    onClick={(e) => {
                      e.stopPropagation();
                      acknowledge.mutate(item);
                    }}
                  >
                    {t("Acknowledge")}
                  </Button>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap gap-3 border-t px-3 py-2 text-xs">
        <Link className="underline" to={`/projects/${projectId}/rules/alerts`}>
          {t("All alerts")}
        </Link>
        <Link className="underline" to={`/projects/${projectId}/rules/events`}>
          {t("All events")}
        </Link>
      </div>
    </aside>
  );
}
