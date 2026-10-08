import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Callout } from "@/components/common/Callout";
import type { ResultDocument } from "@/lib/analyses";

/** How many warnings show before the rest fold: a run over 25 animals carries three quality
 * warnings per animal, and the box was a wall (the pangolin run of 2026-10-08). */
const SHOWN = 8;

/** The data quality and method warnings above a result (plan, sections 8.8 and 9.6). */
export function WarningsCallout({ document }: { document: ResultDocument }) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  if (document.warnings.length === 0) return null;
  const names = new Map(document.subjects.map((s) => [s.id, s.name]));
  const worst = document.warnings.some((w) => w.level === "warning")
    ? "warning"
    : "info";
  const hidden = all ? 0 : Math.max(0, document.warnings.length - SHOWN);
  const shown = hidden > 0 ? document.warnings.slice(0, SHOWN) : document.warnings;
  return (
    <Callout kind={worst}>
      <div className="font-medium">{t("Read with care")}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
        {shown.map((w, i) => (
          <li key={`${w.code}-${w.subject_id ?? ""}-${i}`}>
            {w.subject_id && names.get(w.subject_id)
              ? `${names.get(w.subject_id)}: `
              : ""}
            {w.text}
          </li>
        ))}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          className="mt-1 text-sm underline"
          onClick={() => setAll(true)}
        >
          {t("Show all {{count}} warnings", { count: document.warnings.length })}
        </button>
      )}
    </Callout>
  );
}
