import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { Download, ExternalLink, Laptop } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { detectSystem, FIELD_GUIDE_URL, fieldConnectLink, fieldInstallers } from "@/lib/field";

/**
 * Protect Go, the app for the laptop, from the Offload page (decision D332; Tim, 2026-10-17: the
 * install starts here, users are not technical, and the card says as little as it can). Two
 * buttons: "Open Protect Go", which an installed app answers to with this server filled in and
 * signed in (the button asks the server for a one-time code, decision D333, which the app
 * exchanges for a sign-in of its own), and "Install" with the installer for the visitor's
 * system, the others a link away. One line says which to press; the guide holds the rest.
 */
export function FieldCard() {
  const { t } = useTranslation();
  const system = typeof navigator === "undefined" ? null : detectSystem(navigator.userAgent);
  const [first, ...others] = fieldInstallers(system);
  const server = typeof window === "undefined" ? "" : window.location.origin;
  const open = useMutation({
    mutationFn: () => api.post<{ code: string; expires_in: number }>("/api/v1/auth/go-handoff"),
    onSuccess: ({ code }) => {
      window.location.href = `${fieldConnectLink(server)}&code=${encodeURIComponent(code)}`;
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Laptop className="size-4" /> {t("Protect Go")}
        </CardTitle>
        <CardDescription>
          {t("Reads a station's SD card where there is no connection and uploads the files here when you are back online.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" disabled={open.isPending} onClick={() => open.mutate()}>
            <ExternalLink className="size-4" /> {t("Open Protect Go")}
          </Button>
          <Button asChild size="sm" variant="outline">
            <a href={first.url}>
              <Download className="size-4" />
              {t("Install for {{system}}", { system: first.label })}
            </a>
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {t("Installed already? Open it: it connects to this server and signs you in. Not yet? Install it, then open it from here.")}{" "}
          {others.map((installer) => (
            <span key={installer.system}>
              <a className="underline underline-offset-4" href={installer.url}>
                {installer.label}
              </a>
              {" · "}
            </span>
          ))}
          <a className="underline underline-offset-4" href={FIELD_GUIDE_URL} target="_blank" rel="noreferrer">
            {t("Guide")}
          </a>
        </p>
      </CardContent>
    </Card>
  );
}
