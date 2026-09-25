import { render, screen } from "@testing-library/react";

import type { MoveResult } from "@/api/types";
import { PlanView } from "@/components/devices/MoveToProjectDialog";

const plan: MoveResult = {
  project_id: "p2",
  project_name: "Park B",
  preview: true,
  moved_devices: 1,
  moved_entities: 1,
  attribution_jobs: 0,
  entities: [],
  devices: [
    {
      device_id: "d1",
      name: "SP050969",
      project_id: "p1",
      project_name: "Park A",
      spans: [{ start: "2026-05-03T10:00:00+00:00", end: null }],
      entities_along: [
        { entity_id: "e1", name: "Rhino 14", project_id: "p1", project_name: "Park A", moves: true, reason: null },
      ],
      entities_staying: [
        { entity_id: "e2", name: "Rhino 15", project_id: "p1", project_name: "Park A", moves: false, reason: "another device, SP050970, tracked it" },
      ],
      skipped: null,
      attribution_job_id: null,
    },
    {
      device_id: "d2",
      name: "SP050971",
      project_id: "p2",
      project_name: "Park B",
      spans: [],
      entities_along: [],
      entities_staying: [],
      skipped: "already in this project",
      attribution_job_id: null,
    },
  ],
};

describe("PlanView", () => {
  it("says per device what moves, what comes along, what stays and why, and what is skipped", () => {
    render(<PlanView plan={plan} subject={{ kind: "devices", items: [{ id: "d1", name: "SP050969" }, { id: "d2", name: "SP050971" }] }} />);
    expect(screen.getByText("1 devices and 1 entities move to Park B")).toBeInTheDocument();
    expect(screen.getByText("SP050969")).toBeInTheDocument();
    expect(screen.getByText("Rhino 14 comes along")).toBeInTheDocument();
    expect(screen.getByText("Rhino 15 stays: another device, SP050970, tracked it")).toBeInTheDocument();
    expect(screen.getByText("SP050971: skipped, already in this project")).toBeInTheDocument();
  });
});
