import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, Navigate, useSearchParams } from "react-router";
import { z } from "zod";

import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthShell } from "@/pages/auth/AuthShell";
import { useAuthStore } from "@/stores/auth";

const schema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function LoginPage() {
  const [params] = useSearchParams();
  const { status, login } = useAuthStore();
  const version = useQuery({
    queryKey: queryKeys.version,
    queryFn: () => api.get<{ version: string; commit: string }>("/api/version", { anonymous: true }),
  });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });
  const from = params.get("from");

  if (status === "authenticated") return <Navigate to={from && from.startsWith("/") ? from : "/projects"} replace />;

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await login(values.email, values.password);
    } catch (error) {
      form.setError("root", { message: error instanceof ApiError && error.status === 400 ? "Wrong email or password" : (error as Error).message });
    }
  });

  return (
    <AuthShell
      title="Smart Parks Protect"
      description="Sign in to your project"
      footer={
        <>
          <Link to="/forgot-password" className="underline">Forgot your password?</Link>
          <div className="mt-3 text-xs" data-testid="api-version">
            {version.isPending && "Connecting to the API"}
            {version.isError && "API not reachable"}
            {version.isSuccess && `API ${version.data.version} (${version.data.commit})`}
          </div>
        </>
      }
    >
      {params.get("expired") && <Callout kind="warning">Your session ended. Sign in again.</Callout>}
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        <div className="flex flex-col gap-2">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="username" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
          {form.formState.errors.email && <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!form.formState.errors.password} {...form.register("password")} />
          {form.formState.errors.password && <p className="text-sm text-destructive">{form.formState.errors.password.message}</p>}
        </div>
        {form.formState.errors.root && <Callout kind="error">{form.formState.errors.root.message}</Callout>}
        <Button type="submit" disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthShell>
  );
}
