import { useQuery } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/components/ui/button";
import {
  buildMoved,
  loadedBuild,
  rememberBuild,
  type ServerBuild,
} from "@/lib/build";

/** How often the server is asked which build it is on. Often enough that somebody testing a
 * fix hears about it within a few minutes, seldom enough to be nothing on the server. */
const EVERY_MS = 5 * 60 * 1000;

/**
 * A line that says the page is older than the server, with the way to catch up (Tim,
 * 2026-09-21). The interface is one bundle loaded once, so a tab left open keeps running the
 * code it started with through every deploy, and nothing said so: a fix could be live for an
 * hour while the person testing it still had the old one in front of them.
 *
 * Asked on a timer and whenever the window is looked at again, since coming back to a tab is
 * exactly when a deploy has usually happened. Dismissing it keeps it quiet until the server
 * moves again, so nobody is nagged about a version they chose to stay on.
 */
export function NewVersionBar() {
  const { t } = useTranslation();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const { data } = useQuery({
    queryKey: queryKeys.version,
    queryFn: async () => {
      const seen = await api.get<ServerBuild>("/api/version", {
        anonymous: true,
      });
      // the first answer is the age of this bundle; it is kept outside React, where it
      // belongs, since a reload is what clears it
      rememberBuild(seen);
      return seen;
    },
    refetchInterval: EVERY_MS,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
  const moved = buildMoved(loadedBuild(), data);
  if (!moved || (data && dismissed === data.commit)) return null;
  return (
    <div className="flex items-center gap-2 border-b bg-primary/10 px-2 py-1 text-sm sm:px-3">
      <RefreshCw className="size-4 shrink-0 text-primary" />
      <span className="min-w-0 flex-1 truncate">
        {t(
          "A newer version of Protect is on the server; this page is still the old one.",
        )}
      </span>
      <Button
        type="button"
        size="sm"
        className="h-7 shrink-0"
        onClick={() => window.location.reload()}
      >
        {t("Reload")}
      </Button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="size-7 shrink-0"
        aria-label={t("Not now")}
        title={t("Not now")}
        onClick={() => setDismissed(data?.commit ?? null)}
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}
