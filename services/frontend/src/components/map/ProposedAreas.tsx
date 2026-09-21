import { Combine, Search } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  candidateKind,
  type ProposedArea,
  type ProposedAreas as Proposal,
} from "@/components/map/propose";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatArea } from "@/lib/geodesy";

/** The shortest name worth asking for; the API refuses less. */
const MIN_NAME = 2;

/**
 * The candidates an area was proposed from (phase 33): a click's face and the areas around
 * it (decision D270), or the areas of a name in the map being looked at (D273). Each with its
 * size and what it is, a Use button that puts it in the editor, and the attribution the data
 * comes with.
 */
export function ProposedAreas({
  proposal,
  busy,
  error,
  asked,
  onPick,
  onSearch,
  onCombine,
}: {
  proposal: Proposal | null;
  busy: boolean;
  error: string | null;
  /** What the answer on show came from, so the empty case says the right thing. */
  asked: "click" | "name";
  onPick: (candidate: ProposedArea) => void;
  onSearch: (name: string) => void;
  /** Several ticked areas as one zone (decision D274): four reserves beside each other. */
  onCombine: (candidates: ProposedArea[]) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const search = () => {
    const wanted = name.trim();
    if (wanted.length >= MIN_NAME) onSearch(wanted);
  };
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              search();
            }
          }}
          placeholder={t("Or find an area by name")}
          aria-label={t("Or find an area by name")}
          className="h-8"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8"
          disabled={busy || name.trim().length < MIN_NAME}
          onClick={search}
        >
          <Search className="size-4" /> {t("Find")}
        </Button>
      </div>
      <Body
        proposal={proposal}
        busy={busy}
        error={error}
        asked={asked}
        onPick={onPick}
        onCombine={onCombine}
      />
    </div>
  );
}

function Body({
  proposal,
  busy,
  error,
  asked,
  onPick,
  onCombine,
}: {
  proposal: Proposal | null;
  busy: boolean;
  error: string | null;
  asked: "click" | "name";
  onPick: (candidate: ProposedArea) => void;
  onCombine: (candidates: ProposedArea[]) => void;
}) {
  const { t } = useTranslation();
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const candidates = proposal?.candidates ?? [];
  const chosen = candidates.filter((_, index) => ticked.has(index));
  const tick = (index: number, on: boolean) => {
    const next = new Set(ticked);
    if (on) next.add(index);
    else next.delete(index);
    setTicked(next);
  };
  if (busy)
    return (
      <p className="text-xs text-muted-foreground">
        {asked === "name"
          ? t("Looking for that name on OpenStreetMap…")
          : t("Reading the map around the click…")}
      </p>
    );
  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (!proposal) return null;
  if (proposal.candidates.length === 0)
    return (
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          {asked === "name"
            ? t(
                "No area of that name on the part of the map you are looking at. Move the map to it, or click inside it.",
              )
            : t(
                "Nothing encloses that point on OpenStreetMap. Try another spot, or draw the area.",
              )}
        </p>
        {proposal.narrowed && (
          <p className="text-[11px] text-muted-foreground">
            {t(
              "Only the middle of the view was searched; zoom in for the rest.",
            )}
          </p>
        )}
      </div>
    );
  return (
    <div className="space-y-1">
      <ul className="divide-y rounded-md border text-sm">
        {candidates.map((candidate, index) => (
          <li
            key={`${candidate.kind}-${candidate.osm_id ?? index}`}
            className="flex items-center gap-2 px-2 py-1.5"
          >
            <input
              type="checkbox"
              className="size-4 accent-primary"
              aria-label={t("Combine this one with the others")}
              checked={ticked.has(index)}
              onChange={(e) => tick(index, e.target.checked)}
            />
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
      {chosen.length > 1 && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 w-full"
          onClick={() => {
            onCombine(chosen);
            setTicked(new Set());
          }}
        >
          <Combine className="size-4" />{" "}
          {t("Use {{count}} areas as one zone", { count: chosen.length })}
        </Button>
      )}
      {proposal.narrowed && (
        <p className="text-[11px] text-muted-foreground">
          {t("Only the middle of the view was searched; zoom in for the rest.")}
        </p>
      )}
      <p className="text-[11px] text-muted-foreground">
        {proposal.attribution}
      </p>
    </div>
  );
}
