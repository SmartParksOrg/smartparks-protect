import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import type { DeviceWalk } from "@/api/types";
import { CreatedProgress } from "@/components/admin/WalkProgress";

const walk = (done: number, begun = true): DeviceWalk => ({
  identity_id: "i1",
  external_id: "0016C001F09C74FD",
  device_id: "d1",
  device_name: "SP052271",
  total: 26,
  done,
  begun,
});

/** The dialog after a create that queued `queued` uplinks; `at` is when the summary was read. */
const shown = (walks: DeviceWalk[], at = 2, queued = 26) => (
  <MemoryRouter>
    <CreatedProgress
      walks={walks}
      summaryAt={at}
      queued={queued}
      deviceIds={["d1"]}
    />
  </MemoryRouter>
);

/** Mounted on the summary from before the create, then given the one read after it. */
const afterSummary = (walks: DeviceWalk[], queued = 26) => {
  const view = render(shown([], 1, queued));
  view.rerender(shown(walks, 2, queued));
  return view;
};

describe("CreatedProgress", () => {
  it("shows the decoding at once, before any summary names the walk", () => {
    render(shown([], 1));
    expect(
      screen.getByText("Created. Decoding the retained uplinks: 0 of 26."),
    ).toBeInTheDocument();
  });

  it("says a walk waits behind other work", () => {
    afterSummary([walk(0, false)]);
    expect(
      screen.getByText("Created. Decoding the retained uplinks: 0 of 26."),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting")).toBeInTheDocument();
  });

  it("counts while the decoder works and says when it is done", () => {
    const { rerender } = afterSummary([walk(5)]);
    expect(
      screen.getByText("Created. Decoding the retained uplinks: 5 of 26."),
    ).toBeInTheDocument();
    expect(screen.getByText("5 of 26")).toBeInTheDocument();
    rerender(shown([], 3));
    expect(
      screen.getByText(/the 26 retained uplinks are decoded/),
    ).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SP052271" })).toHaveAttribute(
      "href",
      "/admin/devices/d1",
    );
  });

  it("reads a walk that ended before the first summary as decoded (decision D394)", () => {
    afterSummary([], 3);
    expect(
      screen.getByText(/the 3 retained uplinks are decoded/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Created. No retained uplinks wait for the decoder."),
    ).not.toBeInTheDocument();
  });

  it("says when nothing waited for the decoder", () => {
    render(shown([], 1, 0));
    expect(
      screen.getByText("Created. No retained uplinks wait for the decoder."),
    ).toBeInTheDocument();
  });
});
