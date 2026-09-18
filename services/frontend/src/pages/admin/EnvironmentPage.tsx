import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Satellite } from "lucide-react";

import { api } from "@/api/client";
import type {
  EnvironmentProvider,
  EnvironmentTestResult,
} from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Field } from "@/components/common/FormField";
import { Page, PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useMutationToast } from "@/hooks/useMutationToast";

const KEY = ["admin", "environment", "providers"] as const;

/**
 * Environmental data providers (decision D250). The grazing analysis reads a vegetation index
 * per management area from Copernicus; the account used to live in the server's environment
 * variables, out of reach of the people who run the server. It is set up here, the secret is
 * stored encrypted and never returned, and a change takes effect on the next run.
 */
export function EnvironmentPage() {
  const { t } = useTranslation();
  const providers = useQuery({
    queryKey: KEY,
    queryFn: () =>
      api.get<EnvironmentProvider[]>("/api/v1/admin/environment/providers"),
  });
  const provider = providers.data?.[0];
  const [clientId, setClientId] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState<EnvironmentTestResult | null>(null);
  const save = useMutationToast({
    mutationFn: (body: {
      client_id?: string;
      client_secret?: string;
      enabled?: boolean;
    }) =>
      api.put<EnvironmentProvider>(
        "/api/v1/admin/environment/providers/copernicus",
        { body },
      ),
    invalidate: [KEY],
    success: t("Saved"),
    onSuccess: () => {
      setSecret("");
      setClientId(null);
    },
  });
  const test = useMutationToast({
    mutationFn: () =>
      api.post<EnvironmentTestResult>(
        "/api/v1/admin/environment/providers/copernicus/test",
        {},
      ),
    success: (r) => (r.ok ? t("Connected") : t("The provider refused")),
    onSuccess: (r) => setResult(r),
  });
  const id = clientId ?? provider?.client_id ?? "";
  return (
    <>
      <PageHeader
        title={t("Environmental data")}
        description={t(
          "Where the analyses read landscape layers from. The grazing analysis uses the vegetation index per management area; without an account here it runs exactly as before and says once that there is no layer.",
        )}
      />
      <Page>
        {providers.error && (
          <Callout kind="error">{providers.error.message}</Callout>
        )}
        {!provider ? (
          <p className="text-sm text-muted-foreground">{t("Loading…")}</p>
        ) : (
          <Card className="max-w-2xl">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Satellite className="size-4 text-primary" />
                {provider.label}
              </CardTitle>
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={provider.enabled}
                  disabled={save.isPending}
                  onCheckedChange={(on) => save.mutate({ enabled: on })}
                  aria-label={t("Enabled")}
                />
                {t("Enabled")}
              </label>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <p className="text-muted-foreground">
                {t(
                  "Register at dataspace.copernicus.eu and create an OAuth client with the client credentials flow. Sentinel-2 imagery is free; the openEO processing has a monthly allowance per account.",
                )}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t("Client id")} htmlFor="cop-id">
                  <Input
                    id="cop-id"
                    value={id}
                    autoComplete="off"
                    onChange={(e) => setClientId(e.target.value)}
                  />
                </Field>
                <Field label={t("Client secret")} htmlFor="cop-secret">
                  <Input
                    id="cop-secret"
                    type="password"
                    autoComplete="new-password"
                    value={secret}
                    placeholder={
                      provider.secret_set
                        ? t("stored, type a new one to replace it")
                        : t("not set")
                    }
                    onChange={(e) => setSecret(e.target.value)}
                  />
                </Field>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  disabled={save.isPending}
                  onClick={() =>
                    save.mutate({
                      client_id: id,
                      ...(secret.trim() ? { client_secret: secret } : {}),
                    })
                  }
                >
                  {t("Save")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={test.isPending}
                  onClick={() => test.mutate(undefined)}
                >
                  {test.isPending ? t("Testing…") : t("Test connection")}
                </Button>
                {provider.secret_set && (
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={save.isPending}
                    onClick={() => save.mutate({ client_secret: "" })}
                  >
                    {t("Clear the secret")}
                  </Button>
                )}
              </div>
              {result && (
                <Callout kind={result.ok ? "info" : "error"}>
                  {result.detail}
                </Callout>
              )}
              {!provider.configured && provider.from_environment && (
                <Callout kind="info">
                  {t(
                    "This server also carries the account in its environment variables, which is used while nothing is set here.",
                  )}
                </Callout>
              )}
              {!provider.active && (
                <Callout kind="warning">
                  {t(
                    "No account yet: the grazing analysis runs without the vegetation layer and says so once per run.",
                  )}
                </Callout>
              )}
            </CardContent>
          </Card>
        )}
      </Page>
    </>
  );
}

export default EnvironmentPage;
