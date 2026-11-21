import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { IntegrationLogin, IntegrationTestResult } from "@/api/types";
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
import type { QueryKey } from "@tanstack/react-query";

/** Sign an integration in on its target with a code sent by email (decision D414): the
 * account's address, then the code from the mail. Protect trades the code for the target's
 * token and stores it; nobody sees or copies a token. After the sign-in the connection is
 * tested, so the dialog ends on who is signed in and what that account may do. */
export function SignInDialog({
  projectId,
  integrationId,
  target,
  defaultEmail,
  invalidate,
  open,
  onOpenChange,
}: {
  projectId: string;
  integrationId: string;
  /** The connector's name, as the page shows it. */
  target: string;
  /** The account signed in before, else the person's own address. */
  defaultEmail: string;
  invalidate: QueryKey[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const base = `/api/v1/projects/${projectId}/integrations/${integrationId}`;
  const [email, setEmail] = useState(defaultEmail);
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{
    login: IntegrationLogin;
    test: IntegrationTestResult;
  } | null>(null);
  const send = useMutationToast({
    mutationFn: () =>
      api.post(`${base}/login/code`, { body: { email: email.trim() } }),
    onSuccess: () => {
      setSentTo(email.trim());
      setCode("");
      setError(null);
    },
    onError: (e) => setError(e.message),
  });
  const signIn = useMutationToast({
    mutationFn: async () => {
      const login = await api.post<IntegrationLogin>(`${base}/login`, {
        body: { email: sentTo, code: code.trim() },
      });
      // the test says what the account may do, which a token alone does not
      const test = await api.post<IntegrationTestResult>(`${base}/test`, {
        body: {},
      });
      return { login, test };
    },
    invalidate,
    onSuccess: (result) => {
      setDone(result);
      setError(null);
    },
    onError: (e) => setError(e.message),
  });
  const roles = (done?.test.response?.roles as string[] | undefined) ?? [];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("Sign in to {{target}}", { target })}</DialogTitle>
          <DialogDescription>
            {t(
              "{{target}} mails a code to the account's address. Type it here and Protect stores the sign-in for this integration.",
              { target },
            )}
          </DialogDescription>
        </DialogHeader>
        {done ? (
          <div className="space-y-3 text-sm">
            <Callout kind={done.test.ok ? "success" : "warning"}>
              {t("Signed in as {{account}}.", { account: done.login.account })}{" "}
              {done.test.ok ? "" : done.test.detail}
            </Callout>
            {roles.length > 0 && (
              <p>
                {t("Roles on {{target}}: {{roles}}", {
                  target,
                  roles: roles.join(", "),
                })}
              </p>
            )}
            {done.test.ok &&
              done.test.response?.can_register_animals === false && (
                <Callout kind="warning">
                  {t(
                    "This account may send data but not register entities on {{target}}. Ask its administrator for the role that allows it.",
                    { target },
                  )}
                </Callout>
              )}
          </div>
        ) : sentTo === null ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate();
            }}
          >
            <Field
              label={t("Email address of the account")}
              htmlFor="signin-email"
            >
              <Input
                id="signin-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            {error && <Callout kind="error">{error}</Callout>}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                {t("Cancel")}
              </Button>
              <Button type="submit" disabled={!email.trim() || send.isPending}>
                {send.isPending ? t("Sending…") : t("Send me a code")}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              signIn.mutate();
            }}
          >
            <p className="text-sm">
              {t("A code is on its way to {{email}}.", { email: sentTo })}
            </p>
            <Field label={t("Code from the email")} htmlFor="signin-code">
              <Input
                id="signin-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </Field>
            {error && <Callout kind="error">{error}</Callout>}
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                disabled={send.isPending}
                onClick={() => send.mutate()}
              >
                {t("Send a new code")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSentTo(null);
                  setError(null);
                }}
              >
                {t("Other address")}
              </Button>
              <Button type="submit" disabled={!code.trim() || signIn.isPending}>
                {signIn.isPending ? t("Signing in…") : t("Sign in")}
              </Button>
            </DialogFooter>
          </form>
        )}
        {done && (
          <DialogFooter>
            <Button onClick={() => onOpenChange(false)}>{t("Done")}</Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
