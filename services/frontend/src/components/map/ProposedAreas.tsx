import { useTranslation } from "react-i18next";

import {
  candidateKind,
  type ProposedArea,
  type ProposedAreas as Proposal,
} from "@/components/map/propose";
import { Button } from "@/components/ui/button";
import { formatArea } from "@/lib/geodesy";

/**
 * The candidates a click proposed (phase 33): each with its size and what it is, a Use
 * button that puts it in the editor, and the attribution the data comes with.
 */
export function ProposedAreas({
  proposal,
  busy,
  error,
  onPick,
}: {
  proposal: Proposal | null;
  busy: boolean;
  error: string | null;
  onPick: (candidate: ProposedArea) => void;
}) {
  const { t } = useTranslation();
  if (busy)
    return (
      <p className="text-xs text-muted-foreground">
        {t("Reading the map around the click…")}
      </p>
    );
  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (!proposal) return null;
  if (proposal.candidates.length === 0)
    return (
      <p className="text-xs text-muted-foreground">
        {t(
          "Nothing encloses that point on OpenStreetMap. Try another spot, or draw the area.",
        )}
      </p>
    );
  return (
    <div className="space-y-1">
      <ul className="divide-y rounded-md border text-sm">
        {proposal.candidates.map((candidate, index) => (
          <li
            key={`${candidate.kind}-${candidate.osm_id ?? index}`}
            className="flex items-center gap-2 px-2 py-1.5"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">
                {candidate.kind === "enclosed"
                  ? t("Enclosed by roads and water")
                  : candidate.name}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {formatArea(candidate.area_m2)}
                {candidate.kind !== "enclosed" &&
                  ` · ${candidateKind(candidate)}`}
                {candidate.clipped &&
                  ` · ${t("cut by the edge of the search box")}`}
              </span>
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7"
              onClick={() => onPick(candidate)}
            >
              {t("Use")}
            </Button>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted-foreground">
        {proposal.attribution}
      </p>
    </div>
  );
}
