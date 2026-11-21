import { useTranslation } from "react-i18next";

import type { IntegrationSubject } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TONES: Record<IntegrationSubject["state"], string> = {
  registered: "bg-brand-green-light/40 text-foreground border-transparent",
  history_requested: "bg-brand-blue/50 text-foreground border-transparent",
  sending_history: "bg-brand-blue/50 text-foreground border-transparent",
  held: "bg-brand-sand/50 text-foreground border-transparent",
  failed: "bg-destructive/15 text-destructive border-transparent",
};

/** Where an entity stands with an integration (decision D412), in words: integrated, its
 * history on the way with what still waits, held, or refused. */
export function SubjectStateBadge({
  subject,
}: {
  subject: IntegrationSubject;
}) {
  const { t } = useTranslation();
  const label: Record<IntegrationSubject["state"], string> = {
    registered: t("Integrated"),
    history_requested: t("Preparing history"),
    sending_history:
      subject.history_waiting > 0
        ? t("Sending history, {{count}} to go", {
            count: subject.history_waiting,
          })
        : t("Sending history"),
    held: t("On hold"),
    failed: t("Not registered"),
  };
  return (
    <Badge variant="outline" className={cn("shrink-0", TONES[subject.state])}>
      {label[subject.state]}
    </Badge>
  );
}
