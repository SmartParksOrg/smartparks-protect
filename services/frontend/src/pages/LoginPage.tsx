import { useQuery } from "@tanstack/react-query";

import LogoStacked from "@/assets/brand/logo-stacked.svg?react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface VersionResponse {
  version: string;
  commit: string;
}

async function fetchVersion(): Promise<VersionResponse> {
  const response = await fetch("/api/version");
  if (!response.ok) {
    throw new Error(`GET /api/version failed with ${response.status}`);
  }
  return (await response.json()) as VersionResponse;
}

/**
 * Placeholder login page. Authentication arrives in phase 1; until then the form does nothing and
 * the footer shows which API version answers, which is the first sign the stack is wired up.
 */
export function LoginPage() {
  const version = useQuery({ queryKey: ["version"], queryFn: fetchVersion });

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <LogoStacked className="mb-2 h-28 w-auto text-primary" />
          <CardTitle>Smart Parks Protect</CardTitle>
          <CardDescription>Sign in to your project</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" disabled />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" disabled />
            </div>
            <Button type="submit" disabled>
              Sign in
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Login is not available yet. Authentication is built in phase 1.
            </p>
          </form>
          <p className="mt-6 text-center text-xs text-muted-foreground" data-testid="api-version">
            {version.isPending && "Connecting to the API"}
            {version.isError && "API not reachable"}
            {version.isSuccess && `API ${version.data.version} (${version.data.commit})`}
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
