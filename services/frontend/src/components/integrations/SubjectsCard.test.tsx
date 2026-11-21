import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import type { IntegrationSubjects } from "@/api/types";
import { SubjectsCard } from "@/components/integrations/SubjectsCard";

const answer: IntegrationSubjects = {
  items: [
    {
      entity_id: "e1",
      entity_name: "Konik 3",
      state: "registered",
      sensor_id: "70B3D57ED0001234",
      species: "Equus ferus caballus",
      since: "2026-05-01T08:00:00Z",
    },
    {
      entity_id: "e2",
      entity_name: "Konik 9",
      state: "not_registered",
      sensor_id: "70B3D57ED0009999",
      species: "Equus ferus caballus",
    },
    {
      entity_id: "e3",
      entity_name: "Okapi 1",
      state: "blocked",
      detail: "The target knows no species for this entity",
    },
  ],
};

function show(props: Partial<Parameters<typeof SubjectsCard>[0]> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onHistory = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SubjectsCard
          projectId="p1"
          integrationId="i1"
          target="Target"
          hasEntities
          onHistory={onHistory}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onHistory;
}

afterEach(() => vi.restoreAllMocks());

describe("SubjectsCard", () => {
  it("lists what the target has for each entity and offers both ways to register", async () => {
    vi.spyOn(api, "get").mockResolvedValue(answer);
    const onHistory = show();
    expect(await screen.findByText("Konik 3")).toBeInTheDocument();
    expect(screen.getByText("Registered")).toBeInTheDocument();
    expect(screen.getByText("Not registered")).toBeInTheDocument();
    expect(screen.getByText("Cannot be registered")).toBeInTheDocument();
    expect(
      screen.getByText("The target knows no species for this entity"),
    ).toBeInTheDocument();
    expect(screen.getByText(/sensor 70B3D57ED0009999/)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Send history, then register" }),
    );
    expect(onHistory).toHaveBeenCalled();
    // registering at once asks first: it makes animals on another platform
    fireEvent.click(screen.getByRole("button", { name: "Register now" }));
    expect(
      await screen.findByText("Register 1 on Target?"),
    ).toBeInTheDocument();
  });

  it("offers nothing to register when the target has them all", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ items: [answer.items[0]!] });
    show();
    expect(await screen.findByText("Konik 3")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Register now" }),
    ).not.toBeInTheDocument();
  });

  it("says what the target answered when it refuses the read", async () => {
    vi.spyOn(api, "get").mockRejectedValue(
      new Error("the account lacks the herd-manager role"),
    );
    show();
    expect(
      await screen.findByText("the account lacks the herd-manager role"),
    ).toBeInTheDocument();
  });

  it("asks for entities first and does not call the target without them", () => {
    const get = vi.spyOn(api, "get");
    show({ hasEntities: false });
    expect(
      screen.getByText(/Tick the entities to forward under Edit/),
    ).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });
});
