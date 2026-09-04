import { useTranslation } from "react-i18next";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { api, ApiError } from "@/api/client";
import type { InvitationInfo } from "@/api/types";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/pages/auth/AuthShell";
import { useAuthStore } from "@/stores/auth";

const schema = z
  .object({
    full_name: z.string().max(200).optional(),
    password: z.string().min(10, "At least 10 characters"),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });
type Values = z.infer<typeof schema>;

/** Registration by invitation: the token in the link decides the email and the role. */
export function RegisterPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const invitation = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api.get<InvitationInfo>("/api/v1/auth/invitation", { query: { token }, anonymous: true }),
    enabled: token.length > 0,
    retry: false,
  });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { full_name: "", password: "", confirm: "" } });
  const register = useMutation({
    mutationFn: (values: Values) =>
      api.post("/api/v1/auth/register", { body: { token, password: values.password, full_name: values.full_name || null }, anonymous: true }),
    onSuccess: async (_, values) => {
      if (invitation.data) await login(invitation.data.email, values.password);
      void navigate("/projects", { replace: true });
    },
    onError: (error) => form.setError("root", { message: (error as Error).message }),
  });

  if (!token) return <AuthShell title={t("Invitation needed")}><Callout kind="error">{t("This page needs an invitation link. Ask a project admin to invite you.")}</Callout></AuthShell>;
  if (invitation.isError) {
    const error = invitation.error as ApiError;
    return (
      <AuthShell title={t("Invitation not valid")} footer={<Link to="/login" className="underline">{t("Back to sign in")}</Link>}>
        <Callout kind="error">{error.status === 410 ? "This invitation was used already or has expired." : "This invitation link is not valid."}</Callout>
      </AuthShell>
    );
  }
  const info = invitation.data;
  return (
    <AuthShell
      title={t("Create your account")}
      description={info ? (info.server_admin ? "You are invited as server admin" : `You are invited to ${info.project_name ?? "a project"} as ${info.role?.replace("project-", "")}`) : undefined}
    >
      <form className="flex flex-col gap-4" onSubmit={form.handleSubmit((v) => register.mutate(v))} noValidate>
        <div className="flex flex-col gap-2">
          <Label htmlFor="email">{t("Email")}</Label>
          <Input id="email" value={info?.email ?? ""} disabled readOnly />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="full_name">{t("Name")}</Label>
          <Input id="full_name" autoComplete="name" {...form.register("full_name")} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">{t("Password")}</Label>
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!form.formState.errors.password} {...form.register("password")} />
          {form.formState.errors.password && <p className="text-sm text-destructive">{form.formState.errors.password.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="confirm">{t("Repeat password")}</Label>
          <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!form.formState.errors.confirm} {...form.register("confirm")} />
          {form.formState.errors.confirm && <p className="text-sm text-destructive">{form.formState.errors.confirm.message}</p>}
        </div>
        {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
        <Button type="submit" disabled={register.isPending || !info}>{register.isPending ? "Creating…" : "Create account"}</Button>
      </form>
    </AuthShell>
  );
}
