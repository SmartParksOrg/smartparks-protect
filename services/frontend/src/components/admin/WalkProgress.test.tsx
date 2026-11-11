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

const shown = (walks: DeviceWalk[]) => (
  <MemoryRouter>
    <CreatedProgress walks={walks} deviceIds={["d1"]} />
  </MemoryRouter>
);

describe("CreatedProgress", () => {
  it("says a walk waits behind other work", () => {
    render(shown([walk(0, false)]));
    expect(
      screen.getByText("Created. Decoding the retained uplinks: 0 of 26."),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting")).toBeInTheDocument();
  });

  it("counts while the decoder works and says when it is done", () => {
    const { rerender } = render(shown([walk(5)]));
    expect(
      screen.getByText("Created. Decoding the retained uplinks: 5 of 26."),
    ).toBeInTheDocument();
    expect(screen.getByText("5 of 26")).toBeInTheDocument();
    rerender(shown([]));
    expect(
      screen.getByText(/the 26 retained uplinks are decoded/),
    ).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SP052271" })).toHaveAttribute(
      "href",
      "/admin/devices/d1",
    );
  });

  it("says when nothing waited for the decoder", () => {
    render(shown([]));
    expect(
      screen.getByText("Created. No retained uplinks wait for the decoder."),
    ).toBeInTheDocument();
  });
});
