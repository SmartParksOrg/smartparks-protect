import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";

/** Label, control and error in the same layout everywhere. */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  // a validation message comes from a module-level schema, marked for extraction there
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && !error && (
        <p className="text-xs text-muted-foreground">{hint}</p>
      )}
      {error && <p className="text-sm text-destructive">{t(error)}</p>}
    </div>
  );
}
