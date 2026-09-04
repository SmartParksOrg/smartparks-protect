import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { AiPolicy } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutationToast } from "@/hooks/useMutationToast";
import { formatTime } from "@/lib/format";

const LABELS: Record<string, string> = {
  create_event: "Create an event (report)",
  acknowledge_alert: "Acknowledge an alert",
  request_device_status: "Request a device status",
  request_device_position: "Request a device position",
  high_impact_control: "High-impact control (reset, configuration)",
};
const CLASSES: Record<string, string> = { safe_write: "safe write", operational_control: "operational control", high_impact_control: "high-impact control" };
const MODES: Record<string, string> = { allowed: "allowed at once", confirmation: "needs the person's confirmation", privileged: "needs a project admin and confirmation", disabled: "disabled" };

/** The AI action policy (architecture 27.6): what AI clients may do on a person's behalf,
 * per action class, on top of that person's permissions. */
export function AiPolicyPage() {
  const policy = useQuery({ queryKey: queryKeys.aiPolicy, queryFn: () => api.get<AiPolicy>("/api/v1/admin/ai-policy") });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const stored = policy.data?.policy ?? {};
  const draft = { ...stored, ...edits };
  const save = useMutationToast({ mutationFn: () => api.put<AiPolicy>("/api/v1/admin/ai-policy", { body: { policy: draft } }), invalidate: [queryKeys.aiPolicy], success: "Policy saved", onSuccess: () => setEdits({}) });
  const dirty = Object.entries(edits).some(([k, v]) => stored[k] !== v);
  return (
    <>
      <PageHeader title="AI clients policy" description="What AI clients connected over MCP may do on a person's behalf, beyond reading. The person's own permissions and the granted scopes apply as well." actions={<Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save</Button>} />
      <Page>
        {policy.error && <Callout kind="error">{policy.error.message}</Callout>}
        <Callout kind="info">Reads and analysis are always allowed within the person's access. A write held for confirmation returns a summary to the AI client, which must ask the person before executing it. High-impact control stays disabled for AI clients in this version.</Callout>
        <Card>
          <CardHeader><CardTitle>Actions</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1">Action</th><th>Class</th><th>Scope</th><th>Policy</th></tr></thead>
              <tbody>
                {policy.data?.actions.map((a) => (
                  <tr key={a.action} className="border-t">
                    <td className="py-2">{LABELS[a.action] ?? a.action}</td>
                    <td>{CLASSES[a.action_class] ?? a.action_class}</td>
                    <td className="font-mono text-xs">{a.scope || "none"}</td>
                    <td>
                      {a.action === "high_impact_control" ? <span className="text-muted-foreground">{MODES.disabled}</span> : (
                        <Select value={draft[a.action] ?? a.mode} onValueChange={(v) => setEdits({ ...edits, [a.action]: v })}>
                          <SelectTrigger className="w-72" aria-label={`Policy for ${a.action}`}><SelectValue /></SelectTrigger>
                          <SelectContent>{policy.data?.modes.filter((m) => m !== "disabled" || true).map((m) => <SelectItem key={m} value={m}>{MODES[m] ?? m}</SelectItem>)}</SelectContent>
                        </Select>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {policy.data?.updated_at && <p className="mt-2 text-xs text-muted-foreground">Last changed {formatTime(policy.data.updated_at)}.</p>}
          </CardContent>
        </Card>
      </Page>
    </>
  );
}
