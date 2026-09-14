import { useTranslation } from "react-i18next";

import { Callout } from "@/components/common/Callout";
import type { ResultDocument } from "@/lib/analyses";

/** The data quality and method warnings above a result (plan, sections 8.8 and 9.6). */
export function WarningsCallout({ document }: { document: ResultDocument }) {
  const { t } = useTranslation();
  if (document.warnings.length === 0) return null;
  const names = new Map(document.subjects.map((s) => [s.id, s.name]));
  const worst = document.warnings.some((w) => w.level === "warning")
    ? "warning"
    : "info";
  return (
    <Callout kind={worst}>
      <div className="font-medium">{t("Read with care")}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
        {document.warnings.map((w, i) => (
          <li key={`${w.code}-${w.subject_id ?? ""}-${i}`}>
            {w.subject_id && names.get(w.subject_id)
              ? `${names.get(w.subject_id)}: `
              : ""}
            {w.text}
          </li>
        ))}
      </ul>
    </Callout>
  );
}
