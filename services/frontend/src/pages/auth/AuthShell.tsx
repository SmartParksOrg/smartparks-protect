import { type ReactNode, useState } from "react";

import logoLandscape from "@/assets/brand/logo-landscape.webp";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** The photographs behind the sign-in card, one picked per visit: Smart Parks landscapes by
 * Tim van Dam, used with his permission, blurred in the file itself so the browser blurs
 * nothing, served unhashed from `public/` so a server can swap them without a rebuild. */
const BACKGROUNDS = [
  "/auth-background-1.webp",
  "/auth-background-2.webp",
  "/auth-background-3.webp",
  "/auth-background-4.webp",
];

/** The frame of the sign-in, registration and password pages: the card over a photograph
 * with a dark wash, the way the sister platform frames its sign-in. */
export function AuthShell({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const [background] = useState(
    () => BACKGROUNDS[Math.floor(Math.random() * BACKGROUNDS.length)],
  );
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-muted px-4 py-8">
      <div
        aria-hidden
        className="absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: `url('${background}')` }}
      />
      <div aria-hidden className="absolute inset-0 bg-black/35" />
      <Card className="relative w-full max-w-sm bg-card/95 shadow-2xl backdrop-blur-sm">
        <CardHeader className="justify-items-center text-center">
          <img
            src={logoLandscape}
            alt="Smart Parks"
            className="mb-2 w-56 max-w-full"
          />
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent className="space-y-4">
          {children}
          {footer && (
            <div className="text-center text-sm text-muted-foreground">
              {footer}
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
