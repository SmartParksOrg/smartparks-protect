import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { ConsentDecision, ConsentInfo } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { AuthShell } from "@/pages/auth/AuthShell";
import { useAuthStore } from "@/stores/auth";

/**
 * The OAuth consent screen for AI clients (architecture 27.5). The authorization server (the
 * API) redirects the user's browser here with a request id; the signed-in user approves or
 * denies and the browser is sent back to the client's redirect URI. That last hop is a
 * top-level navigation to another origin, so it is the one place `window.location` is used.
 * A client identified by a metadata document is shown by the host of its client id, because the
 * name inside the document is self-asserted.
 */
export function ConsentPage() {
  const [params] = useSearchParams();
  const requestId = params.get("request") ?? "";
  const user = useAuthStore((s) => s.user);
  const info = useQuery({
    queryKey: queryKeys.oauthConsent(requestId),
    queryFn: () => api.get<ConsentInfo>(`/api/v1/oauth/consent/${requestId}`),
    enabled: requestId !== "",
    retry: false,
  });
  const decide = useMutationToast({
    mutationFn: (decision: "approve" | "deny") => api.post<ConsentDecision>(`/api/v1/oauth/consent/${requestId}/${decision}`),
    onSuccess: (data) => window.location.assign(data.redirect_to),
  });

  if (!requestId) {
    return (
      <AuthShell title="Connect an AI client">
        <Callout kind="error">This page needs an authorization request. Start the connection from the AI client again.</Callout>
      </AuthShell>
    );
  }
  if (info.isPending) {
    return <AuthShell title="Connect an AI client"><p className="text-center text-sm text-muted-foreground">Loading the request…</p></AuthShell>;
  }
  if (info.isError) {
    return (
      <AuthShell title="Connect an AI client">
        <Callout kind="error">{info.error.message}</Callout>
      </AuthShell>
    );
  }
  const c = info.data;
  const clientLabel = c.registration === "metadata_document" ? c.client_host ?? c.client_id : c.client_name ?? c.client_id;
  return (
    <AuthShell title="Connect an AI client" description={`Signed in as ${user?.email ?? ""}`}>
      <div className="space-y-3 text-sm">
        <p>
          <span className="font-medium">{clientLabel}</span> asks for read access to your Smart Parks Protect data.
          {c.registration === "metadata_document" && c.client_name && <span className="text-muted-foreground"> It calls itself “{c.client_name}”.</span>}
        </p>
        <div className="rounded-md border bg-muted/40 px-3 py-2">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">It may</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {c.scopes.map((s) => (
              <li key={s.key}>{s.description}</li>
            ))}
          </ul>
        </div>
        <p className="text-muted-foreground">
          After approval you return to <span className="font-mono">{c.redirect_host}</span>. Everything the client reads is done as you and recorded in the audit log. You can disconnect it later under Connected AI clients.
        </p>
        {c.loopback_redirect && (
          <Callout kind="warning">The client runs on this computer (it returns to {c.redirect_host}). Approve only if you started this connection yourself.</Callout>
        )}
        <div className="flex gap-2">
          <Button className="flex-1" onClick={() => decide.mutate("approve")} disabled={decide.isPending}>Allow</Button>
          <Button className="flex-1" variant="outline" onClick={() => decide.mutate("deny")} disabled={decide.isPending}>Deny</Button>
        </div>
      </div>
    </AuthShell>
  );
}
