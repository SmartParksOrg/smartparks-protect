import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import type { Deployment, DeviceIntegration } from "@/api/types";
import { DeploymentList } from "@/components/integrations/DeploymentList";
import { DeviceIntegrationsCard } from "@/components/integrations/DeviceIntegrationsCard";

const deployment = (more: Partial<Deployment> = {}): Deployment => ({
  id: "d1",
  integration_id: "i1",
  entity_id: "e2",
  entity_name: "Cow 13",
  device_id: "x1",
  device_name: "SP051463",
  sensor_id: "0016C001F016D24A",
  starts_at: "2026-11-20T10:00:00Z",
  state: "pending",
  open_on_target: false,
  rewrites: 0,
  ...more,
});

function show(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("DeploymentList", () => {
  it("asks before a moved device goes to the other animal, and warns about the platform's fault", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue(deployment({ state: "sent" }));
    show(
      <DeploymentList
        projectId="p1"
        target="WildlifeNL"
        canWrite
        deployments={[
          deployment({ rewrites: 1 }),
          deployment({
            id: "d0",
            entity_id: "e1",
            entity_name: "Cow 12",
            state: "sent",
            starts_at: "2026-09-08T14:32:33Z",
            ends_at: "2026-11-20T10:00:00Z",
            open_on_target: true,
          }),
        ]}
      />,
    );
    expect(screen.getByText("Waits for you")).toBeTruthy();
    // the device left Cow 12 and the target cannot end that deployment
    expect(screen.getByText(/keeps the sensor on this animal/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText(/sets its end to this start/)).toBeTruthy();
    expect(screen.getByText(/cannot be removed/)).toBeTruthy();
    const buttons = screen.getAllByRole("button", { name: "Confirm" });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/projects/p1/integrations/i1/deployments/d1/confirm",
      ),
    );
  });

  it("declines, and a viewer only reads", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValue(deployment({ state: "declined" }));
    show(
      <DeploymentList
        projectId="p1"
        target="WildlifeNL"
        canWrite
        deployments={[
          deployment({ state: "refused", detail: "422 Unprocessable" }),
        ]}
      />,
    );
    expect(screen.getByText("422 Unprocessable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(await screen.findByText(/is not sent either/)).toBeTruthy();
    const buttons = screen.getAllByRole("button", { name: "Decline" });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/projects/p1/integrations/i1/deployments/d1/decline",
      ),
    );
  });

  it("shows no buttons to a viewer", () => {
    show(
      <DeploymentList
        projectId="p1"
        target="WildlifeNL"
        canWrite={false}
        deployments={[deployment()]}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("DeviceIntegrationsCard", () => {
  it("shows the entity the device is on and integrates it from the device", async () => {
    const answer: DeviceIntegration[] = [
      {
        integration_id: "i1",
        name: "WildlifeNL",
        connector_key: "wildlifenl",
        connector_label: "WildlifeNL",
        enabled: true,
        entity_id: "e2",
        entity_name: "Cow 13",
        subject: null,
        deployments: [],
      },
    ];
    vi.spyOn(api, "get").mockResolvedValue(answer);
    show(<DeviceIntegrationsCard projectId="p1" deviceId="x1" canWrite />);
    expect(await screen.findByRole("link", { name: "Cow 13" })).toBeTruthy();
    expect(screen.getByText("Not integrated")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Integrate" })).toBeTruthy();
  });

  it("says so when the device is on no entity", async () => {
    vi.spyOn(api, "get").mockResolvedValue([
      {
        integration_id: "i1",
        name: "WildlifeNL",
        connector_key: "wildlifenl",
        connector_label: "WildlifeNL",
        enabled: true,
        entity_id: null,
        subject: null,
        deployments: [],
      },
    ]);
    show(<DeviceIntegrationsCard projectId="p1" deviceId="x1" canWrite />);
    expect(await screen.findByText(/on no entity/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Integrate" })).toBeNull();
  });
});
