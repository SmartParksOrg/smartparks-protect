import { render, screen } from "@testing-library/react";

import { AreaCards } from "@/components/analysis/AreaCards";
import { RestStrip } from "@/components/analysis/RestStrip";
import { SubjectCards } from "@/components/analysis/SubjectCards";
import type { ResultDocument } from "@/lib/analyses";

const base = {
  version: 1,
  method_version: "x/1",
  tables: [],
  geometries: {},
  warnings: [],
  provenance: {},
};

const movement: ResultDocument = {
  ...base,
  module: "movement",
  subjects: [{ id: "a", name: "Aldo", type: "Elephant" }],
  periods: [
    { key: "main", time_from: "2026-08-15T00:00:00Z", time_to: "2026-09-14T00:00:00Z" },
    { key: "comparison", time_from: "2026-07-16T00:00:00Z", time_to: "2026-08-15T00:00:00Z" },
  ],
  summary: {
    main: { a: { distance_km: 123.456, stationary_share: 0.42, fixes: 720, mcp95_ha: null } },
    comparison: { a: { distance_km: 99, stationary_share: 0.5, fixes: 700, mcp95_ha: 12 } },
  },
  charts: [],
};

const grazing: ResultDocument = {
  ...base,
  module: "grazing",
  subjects: [{ id: "a", name: "Aldo" }],
  periods: [{ key: "main", time_from: "2026-09-11T00:00:00Z", time_to: "2026-09-14T00:00:00Z" }],
  summary: {
    herd: { main: { tracked_animal_hours: 71.5, share_inside: 0.8, share_outside: 0.2 } },
    weighting: { kind: "attribute", key: "lsu", unit: "lsu units" },
    areas: [
      { id: "z1", name: "Camp 1", kind: "zone", hectares: 10.04 },
      { id: "z2", name: "Camp 2", kind: "zone", hectares: 40 },
    ],
    main: {
      z1: {
        animal_days_per_ha: 0.2,
        relative_pressure: 2,
        pressure_rank: 1,
        animals_used: 1,
        use_days: 2,
        rest_days: 1,
        longest_rest_days: 1,
        hours_since_last_use: 30,
      },
    },
  },
  charts: [
    {
      key: "timeline",
      kind: "line",
      unit: "animal-hours",
      series: [
        {
          name: "Camp 1",
          area: "z1",
          period: "main",
          data: [
            [1_757_548_800_000, 24],
            [1_757_635_200_000, 0],
            [1_757_721_600_000, 12],
          ],
        },
      ],
    },
  ],
};

describe("analysis cards", () => {
  it("shows a subject's figures with the comparison beside them", () => {
    render(
      <SubjectCards
        document={movement}
        labels={{ distance_km: "Distance (km)", stationary_share: "Stationary", fixes: "Fixes", mcp95_ha: "MCP" }}
        metrics={[
          ["distance_km", "km"],
          ["stationary_share", "%"],
          ["fixes", ""],
          ["mcp95_ha", "ha"],
        ]}
      />,
    );
    expect(screen.getByText("Aldo")).toBeInTheDocument();
    expect(screen.getByText("Elephant")).toBeInTheDocument();
    expect(screen.getByText(/123 km/)).toBeInTheDocument();
    expect(screen.getByText(/42%/)).toBeInTheDocument();
    expect(screen.getByText(/before 99.0 km/)).toBeInTheDocument();
    expect(screen.getByText(/–/)).toBeInTheDocument();
  });
  it("shows the herd line and a card per area, unused ones too", () => {
    render(
      <AreaCards
        document={grazing}
        labels={{
          animal_days_per_ha: "Use",
          relative_pressure: "Pressure",
          animals_used: "Animals",
          use_days: "Use days",
          longest_rest_days: "Longest rest",
          hours_since_last_use: "Since last use",
        }}
      />,
    );
    expect(screen.getByText(/72 animal-hours; 80% of that time inside/)).toBeInTheDocument();
    expect(screen.getByText(/Weighted in lsu units/)).toBeInTheDocument();
    expect(screen.getByText("Camp 1")).toBeInTheDocument();
    expect(screen.getByText("2.00 (#1)")).toBeInTheDocument();
    expect(screen.getByText("Camp 2")).toBeInTheDocument();
    expect(screen.getByText("Not used.")).toBeInTheDocument();
  });
  it("draws a cell per day with the rest days empty", () => {
    const { container } = render(<RestStrip document={grazing} restThreshold={0} />);
    expect(screen.getByText("Use and rest by day")).toBeInTheDocument();
    const cells = container.querySelectorAll("tbody td span");
    expect(cells).toHaveLength(3);
    expect((cells[1] as HTMLElement).style.backgroundColor).toBe("transparent");
    expect((cells[0] as HTMLElement).style.backgroundColor).not.toBe("transparent");
  });
});
