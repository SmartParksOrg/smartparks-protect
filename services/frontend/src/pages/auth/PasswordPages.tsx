import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";

import { api } from "@/api/client";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/pages/auth/AuthShell";

const emailSchema = z.object({ email: z.email("Enter a valid email address") });

export function ForgotPasswordPage() {
  const form = useForm<z.infer<typeof emailSchema>>({ resolver: zodResolver(emailSchema), defaultValues: { email: "" } });
  const request = useMutation({
    mutationFn: (values: { email: string }) => api.post("/api/v1/auth/forgot-password", { body: values, anonymous: true }),
  });
  return (
    <AuthShell title="Reset your password" description="We send a link to your email address" footer={<Link to="/login" className="underline">Back to sign in</Link>}>
      {request.isSuccess ? (
        <Callout kind="success">If an account exists for this address, a reset link is on its way.</Callout>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={form.handleSubmit((v) => request.mutate(v))} noValidate>
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="username" {...form.register("email")} />
            {form.formState.errors.email && <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>}
          </div>
          <Button type="submit" disabled={request.isPending}>Send reset link</Button>
        </form>
      )}
    </AuthShell>
  );
}

const resetSchema = z
  .object({ password: z.string().min(10, "At least 10 characters"), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const form = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema), defaultValues: { password: "", confirm: "" } });
  const reset = useMutation({
    mutationFn: (values: { password: string }) => api.post("/api/v1/auth/reset-password", { body: { token, password: values.password }, anonymous: true }),
    onSuccess: () => void navigate("/login", { replace: true }),
    onError: (error) => form.setError("root", { message: (error as Error).message }),
  });
  if (!token) return <AuthShell title="Reset link needed"><Callout kind="error">Open the link from the reset email.</Callout></AuthShell>;
  return (
    <AuthShell title="Choose a new password">
      <form className="flex flex-col gap-4" onSubmit={form.handleSubmit((v) => reset.mutate(v))} noValidate>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">New password</Label>
          <Input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
          {form.formState.errors.password && <p className="text-sm text-destructive">{form.formState.errors.password.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="confirm">Repeat password</Label>
          <Input id="confirm" type="password" autoComplete="new-password" {...form.register("confirm")} />
          {form.formState.errors.confirm && <p className="text-sm text-destructive">{form.formState.errors.confirm.message}</p>}
        </div>
        {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
        <Button type="submit" disabled={reset.isPending}>Set password</Button>
      </form>
    </AuthShell>
  );
}
