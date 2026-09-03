import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { SystemHealth } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatAgo } from "@/lib/format";

export function HealthPage() {
  const health = useQuery({ queryKey: queryKeys.systemHealth, queryFn: () => api.get<SystemHealth>("/api/v1/system/health"), refetchInterval: 15_000 });
  const h = health.data;
  return (
    <>
      <PageHeader title="System health" description="Pipeline state: workers, throughput, failures, data sources" actions={h && <StatusBadge value={h.status} />} />
      <Page>
        {health.isError && <Callout kind="error">{health.error.message}</Callout>}
        {h && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">Events per minute</div><div className="text-2xl font-semibold">{h.events_per_minute}</div></CardContent></Card>
              <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">Failed, last hour</div><div className="text-2xl font-semibold">{h.failed_last_hour}</div></CardContent></Card>
              <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">Unassigned, last hour</div><div className="text-2xl font-semibold">{h.unassigned_last_hour}</div></CardContent></Card>
              <Card><CardContent className="pt-4"><div className="text-xs text-muted-foreground">Unknown identities</div><div className="text-2xl font-semibold">{h.unknown_identities}</div></CardContent></Card>
            </div>
            <Card>
              <CardHeader><CardTitle>Workers</CardTitle></CardHeader>
              <CardContent>
                <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-muted-foreground"><th className="py-1">Worker</th><th>Heartbeat</th><th>Stream lag</th><th>Dead letters</th></tr></thead><tbody>
                  {h.workers.map((w) => <tr key={w.name} className="border-t"><td className="py-1.5 font-medium">{w.name}</td><td>{w.stale ? <span className="text-destructive">stale, {formatAgo(w.last_heartbeat)}</span> : formatAgo(w.last_heartbeat)}</td><td>{w.lag ?? ""}</td><td>{w.dead_letters ?? ""}</td></tr>)}
                </tbody></table></div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Data sources</CardTitle></CardHeader>
              <CardContent>
                <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-muted-foreground"><th className="py-1">Source</th><th>Adapter</th><th>Enabled</th><th>Events, last hour</th><th>Last event</th></tr></thead><tbody>
                  {h.data_sources.map((s) => <tr key={s.id} className="border-t"><td className="py-1.5 font-medium">{s.name}</td><td>{s.adapter_key}</td><td>{s.enabled ? "yes" : "no"}</td><td>{s.events_last_hour}</td><td>{formatAgo(s.last_event_at)}</td></tr>)}
                </tbody></table></div>
              </CardContent>
            </Card>
            {Object.keys(h.dead_letters).length > 0 && <Callout kind="warning">Dead letters: {Object.entries(h.dead_letters).map(([t, n]) => `${t} (${n})`).join(", ")}. Handle them under Needs attention.</Callout>}
          </>
        )}
      </Page>
    </>
  );
}
