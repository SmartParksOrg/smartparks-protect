import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";

/** What the page shows when a render failed: the words, the error for a report, a way out.
 * Without it React unmounts everything and the person sees a white page (Tim, 2026-11-08,
 * when the live map's panel looped at the minute mark). */
function Fallback({ error }: { error: Error }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-6 text-center">
      <TriangleAlert className="size-8 text-brand-coral" />
      <div className="text-lg font-medium">{t("Something went wrong")}</div>
      <p className="max-w-md text-sm text-muted-foreground">
        {t(
          "The page could not be drawn. Reload to try again; if it happens again, send the line below to the people who run this server.",
        )}
      </p>
      <code className="max-w-full overflow-x-auto rounded bg-muted px-2 py-1 text-left text-xs">
        {error.message}
      </code>
      <div className="flex gap-2">
        <Button onClick={() => window.location.reload()}>{t("Reload")}</Button>
        <Button variant="outline" asChild>
          <a href="/projects">{t("Back to the projects")}</a>
        </Button>
      </div>
    </div>
  );
}

interface State {
  error: Error | null;
}

/** Catches a render or effect error anywhere under it and shows `Fallback` in its place. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Render failed", error, info.componentStack);
  }

  render() {
    if (this.state.error) return <Fallback error={this.state.error} />;
    return this.props.children;
  }
}
