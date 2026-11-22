import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import type {
  EntityIntegration,
  IntegrationSubject,
  IntegrationSubjectOptions,
  IntegrationSubjects,
} from "@/api/types";
import { EntityIntegrationsCard } from "@/components/integrations/EntityIntegrationsCard";
import { IntegrateEntityDialog } from "@/components/integrations/IntegrateEntityDialog";
import { SubjectsCard } from "@/components/integrations/SubjectsCard";

const subject = (
  more: Partial<IntegrationSubject> = {},
): IntegrationSubject => ({
  integration_id: "i1",
  entity_id: "e1",
  entity_name: "Cow 12",
  state: "registered",
  species_id: "s1",
  species_name: "Bos taurus",
  history_queued: 0,
  history_waiting: 0,
  created_at: "2026-11-21T10:00:00Z",
  ...more,
});

const options: IntegrationSubjectOptions = {
  entity_id: "e1",
  entity_name: "Cow 12",
  device_name: "SP051463",
  assigned_from: "2026-09-08T14:32:33Z",
  sensor_id: "0016C001F016D24A",
  target: { registered: false },
  species: [
    { id: "s1", name: "Bos taurus", common_name: "Rund" },
    { id: "s2", name: "Equus ferus caballus", common_name: "Paard" },
  ],
  proposed_species_id: null,
};

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

describe("SubjectsCard", () => {
  it("shows each integrated entity with what the target has, and changes nothing", async () => {
    const answer: IntegrationSubjects = {
      items: [
        subject({
          target: {
            registered: true,
            sensor_id: "0016C001F016D24A",
            external_name: "Cow 12",
          },
        }),
        subject({
          entity_id: "e2",
          entity_name: "Cow 13",
          state: "sending_history",
          history_waiting: 40,
          target: { registered: false, sensor_id: "0016C001F016D24B" },
        }),
        subject({
          entity_id: "e3",
          entity_name: "Cow 14",
          state: "held",
          detail: "2 objects of its history failed.",
        }),
      ],
    };
    vi.spyOn(api, "get").mockResolvedValue(answer);
    show(<SubjectsCard projectId="p1" integrationId="i1" target="Target" />);
    expect(await screen.findByText("Cow 12")).toBeInTheDocument();
    expect(screen.getByText("Integrated")).toBeInTheDocument();
    expect(screen.getByText("Sending history, 40 to go")).toBeInTheDocument();
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(
      screen.getByText("2 objects of its history failed."),
    ).toBeInTheDocument();
    expect(screen.getByText(/on Target as Cow 12/)).toBeInTheDocument();
    expect(screen.getByText(/not on Target yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says where to integrate when nothing is, and what the target answered when it refuses", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ items: [] });
    show(<SubjectsCard projectId="p1" integrationId="i1" target="Target" />);
    expect(
      await screen.findByText(/No entity is integrated yet/),
    ).toBeInTheDocument();
  });

  it("keeps Protect's own rows when the target cannot be asked", async () => {
    vi.spyOn(api, "get").mockResolvedValue({
      items: [subject()],
      target_error: "the account lacks the herd-manager role",
    });
    show(<SubjectsCard projectId="p1" integrationId="i1" target="Target" />);
    expect(await screen.findByText("Cow 12")).toBeInTheDocument();
    expect(
      screen.getByText(/the account lacks the herd-manager role/),
    ).toBeInTheDocument();
  });
});

describe("EntityIntegrationsCard", () => {
  const integration = (
    more: Partial<EntityIntegration> = {},
  ): EntityIntegration => ({
    integration_id: "i1",
    name: "WildlifeNL TEST",
    connector_key: "x",
    connector_label: "Target",
    enabled: true,
    ...more,
  });

  it("renders nothing in a project without an integration that registers entities", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue([]);
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <EntityIntegrationsCard projectId="p1" entityId="e1" canWrite />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("offers Integrate to those who may, and only the state to the others", async () => {
    vi.spyOn(api, "get").mockResolvedValue([integration()]);
    show(
      <EntityIntegrationsCard projectId="p1" entityId="e1" canWrite={false} />,
    );
    expect(await screen.findByText("Not integrated")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Integrate" }),
    ).not.toBeInTheDocument();
  });

  it("shows an integrated entity with Change and Stop", async () => {
    vi.spyOn(api, "get").mockResolvedValue([
      integration({
        subject: subject({ registered_at: "2026-11-21T11:00:00Z" }),
      }),
    ]);
    show(<EntityIntegrationsCard projectId="p1" entityId="e1" canWrite />);
    expect(await screen.findByText("Integrated")).toBeInTheDocument();
    expect(screen.getByText(/Bos taurus/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(
      await screen.findByText("Stop forwarding to Target?"),
    ).toBeInTheDocument();
  });
});

describe("IntegrateEntityDialog", () => {
  const open = (answer: IntegrationSubjectOptions) => {
    vi.spyOn(api, "get").mockResolvedValue(answer);
    const put = vi
      .spyOn(api, "put")
      .mockResolvedValue(subject({ state: "history_requested" }));
    show(
      <IntegrateEntityDialog
        projectId="p1"
        entityId="e1"
        integrationId="i1"
        target="Target"
        open
        onOpenChange={() => {}}
      />,
    );
    return put;
  };

  it("asks for a species when none is proposed and sends the history from the assignment", async () => {
    const put = open(options);
    expect(
      await screen.findByText("Integrate Cow 12 with Target"),
    ).toBeInTheDocument();
    expect(screen.getByText("0016C001F016D24A")).toBeInTheDocument();
    expect(screen.getByText(/No match was found/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Integrate" })).toBeDisabled();
    expect(screen.getByLabelText("History from")).toHaveValue("2026-09-08");
    expect(put).not.toHaveBeenCalled();
  });

  it("starts from Protect's proposal and sends what was chosen", async () => {
    const put = open({ ...options, proposed_species_id: "s1" });
    expect(
      await screen.findByText(/Proposed from the entity's type/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch"));
    fireEvent.click(screen.getByRole("button", { name: "Integrate" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0]![1]).toEqual({
      body: {
        species_id: "s1",
        species_name: "Bos taurus",
        attributes: {},
        new_animal: false,
        history_from: null,
      },
    });
  });

  it("asks the ear tag number when the target needs it (D422)", async () => {
    const put = open({
      ...options,
      proposed_species_id: "s1",
      fields: [{ key: "ear_tag", label: "Ear tag number", value: null }],
    });
    const input = await screen.findByLabelText("Ear tag number");
    expect(screen.getByText(/uses it as the animal's identifier/)).toBeTruthy();
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("button", { name: "Integrate" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "NL123456789012" } });
    fireEvent.click(screen.getByRole("button", { name: "Integrate" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0]![1]).toMatchObject({
      body: { attributes: { ear_tag: "NL123456789012" } },
    });
  });

  it("locks species and ear tag once the animal exists, and corrects them with a new animal (D423)", async () => {
    const put = open({
      ...options,
      proposed_species_id: "s1",
      target: {
        registered: true,
        external_name: "NL999900051463",
        external_species: "Egel (Erinaceus europaeus)",
        since: "2026-09-08T14:32:33Z",
      },
      fields: [
        { key: "ear_tag", label: "Ear tag number", value: "NL999900051463" },
      ],
      subject: {
        integration_id: "i1",
        entity_id: "e1",
        entity_name: "Cow 12",
        state: "registered",
        species_id: "s1",
        species_name: "Bos taurus",
        external_id: "a1",
        history_queued: 0,
        history_waiting: 0,
        created_at: "2026-11-22T10:00:00Z",
      },
    });
    // what the target has differs from Protect: said, and the fields are locked
    expect(
      await screen.findByText(/Protect has Bos taurus/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ear tag number")).toBeDisabled();
    fireEvent.click(screen.getByRole("switch", { name: /Make a new animal/ }));
    expect(screen.getByLabelText("Ear tag number")).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Make a new animal" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0]![1]).toMatchObject({
      body: { species_id: "s1", new_animal: true, history_from: null },
    });
  });

  it("says why an entity cannot be integrated and does not let it through", async () => {
    open({
      ...options,
      proposed_species_id: "s1",
      blocked: "No device is on this entity",
    });
    expect(
      await screen.findByText("No device is on this entity"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Integrate" })).toBeDisabled();
  });
});
