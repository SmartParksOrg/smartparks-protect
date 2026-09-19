import { useTranslation } from "react-i18next";

import type { ResultDocument } from "@/lib/analyses";

/** What the run found, before the tables: how many of the possible pairs met, on what evidence,
 * and what was set aside. The evidence split is the figure to read first — a study whose pairs
 * are all proximity rests on how often the animals report, and one whose pairs are all Bluetooth
 * has no independent check on any of them. */
export function ContactSummary({ document }: { document: ResultDocument }) {
  const { t } = useTranslation();
  const s = document.summary as {
    pairs_met?: number;
    pairs_possible?: number;
    contacts?: number;
    hours?: number;
    by_evidence?: Record<string, number>;
    unknown_sightings?: number;
    ambiguous_sightings?: number;
  };
  const evidence = s.by_evidence ?? {};
  const figures: [string, string | number][] = [
    [t("Pairs that met"), `${s.pairs_met ?? 0} / ${s.pairs_possible ?? 0}`],
    [t("Contacts"), s.contacts ?? 0],
    [t("Hours together"), s.hours ?? 0],
    [t("Both kinds of evidence"), evidence["bluetooth + proximity"] ?? 0],
    [t("Bluetooth only"), evidence.bluetooth ?? 0],
    [t("Proximity only"), evidence.proximity ?? 0],
  ];
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        {figures.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      {s.unknown_sightings || s.ambiguous_sightings ? (
        <p className="text-xs text-muted-foreground">
          {t("Set aside:")}{" "}
          {t(
            "{{unknown}} sightings of a neighbour no device of the project matches, {{ambiguous}} whose address could be more than one device.",
            {
              unknown: s.unknown_sightings ?? 0,
              ambiguous: s.ambiguous_sightings ?? 0,
            },
          )}
        </p>
      ) : null}
    </div>
  );
}
