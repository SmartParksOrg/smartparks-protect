import type { ReactNode } from "react";

import LogoStacked from "@/assets/brand/logo-stacked.svg?react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function AuthShell({ title, description, children, footer }: { title: string; description?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <LogoStacked className="mb-2 h-24 w-auto text-primary" />
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent className="space-y-4">
          {children}
          {footer && <div className="text-center text-sm text-muted-foreground">{footer}</div>}
        </CardContent>
      </Card>
    </main>
  );
}
