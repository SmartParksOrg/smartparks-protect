import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { useTechnicalDetails } from "@/hooks/useTechnicalDetails";

/** The part of a page a ranger does not need: identities, ports, traces, provider fields
 * (decision D105). Folded unless the person's preference says otherwise; one click opens it
 * for this page, the switch in the sidebar opens it everywhere. */
export function TechnicalDetails({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  const [preferred] = useTechnicalDetails();
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? preferred;
  return (
    <section className={className} aria-label={t("Technical details")}>
      <Button
        variant="ghost"
        size="sm"
        className="mb-2 h-8 gap-2 px-2 text-muted-foreground"
        aria-expanded={shown}
        onClick={() => setOpen(!shown)}
      >
        {shown ? (
          <ChevronDown className="size-4" />
        ) : (
          <ChevronRight className="size-4" />
        )}
        <Wrench className="size-4" />
        {t("Technical details")}
        {!shown && (
          <span className="text-xs font-normal">
            {t("identities, traffic, provenance")}
          </span>
        )}
      </Button>
      {shown && <div className="grid gap-4 lg:grid-cols-2">{children}</div>}
    </section>
  );
}
