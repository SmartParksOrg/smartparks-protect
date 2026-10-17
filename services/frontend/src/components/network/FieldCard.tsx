import { useTranslation } from "react-i18next";
import { Copy, Download, ExternalLink, Laptop } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { detectSystem, FIELD_GUIDE_URL, fieldConnectLink, fieldInstallers } from "@/lib/field";

/**
 * Protect Go, the app for the laptop, from the Offload page (decision D332; Tim, 2026-10-17: the
 * install starts here, users are not technical; named Protect Go the same day). The installer
 * for the visitor's system first, the others behind it, the server address to type during the
 * app's setup with a copy button, and "Open Protect Go", which an installed app answers to with
 * this server filled in; a browser with no app installed does nothing with the link, which the
 * hint says.
 */
export function FieldCard() {
  const { t } = useTranslation();
  const system = typeof navigator === "undefined" ? null : detectSystem(navigator.userAgent);
  const [first, ...others] = fieldInstallers(system);
  const server = typeof window === "undefined" ? "" : window.location.origin;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Laptop className="size-4" /> {t("Protect Go, the app for the laptop")}
        </CardTitle>
        <CardDescription>
          {t(
            "Protect Go reads a station's SD card on a laptop where there is no connection, with Protect's own decoding, and uploads the files to this server when you are back online. Install the app on the laptop you take to the stations.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild size="sm">
            <a href={first.url}>
              <Download className="size-4" />
              {t("Download for {{system}}", { system: first.label })}
            </a>
          </Button>
          <span className="text-xs text-muted-foreground">
            {first.note} · <code>{first.file}</code>
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          {t("Other systems:")}{" "}
          {others.map((installer, index) => (
            <span key={installer.system}>
              {index > 0 && ", "}
              <a className="underline underline-offset-4" href={installer.url}>
                {installer.label}
              </a>{" "}
              ({installer.note})
            </span>
          ))}
        </p>
        <div>
          <p className="font-medium">{t("During the app's setup, give it this server:")}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <code className="rounded bg-muted px-2 py-1">{server}</code>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label={t("Copy the server address")}
              onClick={() => {
                void navigator.clipboard.writeText(server);
                toast.success(t("Server address copied"));
              }}
            >
              <Copy className="size-4" />
            </Button>
            <Button asChild variant="outline" size="sm">
              <a href={fieldConnectLink(server)}>
                <ExternalLink className="size-4" /> {t("Open Protect Go")}
              </a>
            </Button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("\"Open Protect Go\" starts the installed app with this server filled in; it does nothing until the app is installed. Then sign in with your Protect email and password.")}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          <a className="underline underline-offset-4" href={FIELD_GUIDE_URL} target="_blank" rel="noreferrer">
            {t("How to install and use Protect Go, step by step")}
          </a>
        </p>
      </CardContent>
    </Card>
  );
}
