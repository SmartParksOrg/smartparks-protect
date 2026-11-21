import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EntityField } from "@/api/types";
import { EntityDetailsCard } from "@/components/entities/EntityDetailsCard";
import { EntityFieldInputs } from "@/components/entities/EntityFieldInputs";

const base = {
  choices: [],
  panel: false,
  search: false,
  origin: "standard" as const,
  inherited: false,
};
const fields: EntityField[] = [
  {
    ...base,
    key: "vhf_frequency_mhz",
    label: "VHF frequency",
    kind: "number",
    unit: "MHz",
  },
  { ...base, key: "ear_tag", label: "Ear tag number", kind: "text" },
];

describe("EntityFieldInputs", () => {
  it("shows an input per field of the type with its unit and value", () => {
    render(
      <EntityFieldInputs
        fields={fields}
        draft={{ vhf_frequency_mhz: 148.32 }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByLabelText("VHF frequency (MHz)")).toHaveValue("148.32");
    expect(screen.getByLabelText("Ear tag number")).toHaveValue("");
  });

  it("reports what is typed with the rest of the document", () => {
    const onChange = vi.fn();
    render(
      <EntityFieldInputs
        fields={fields}
        draft={{ species: "Diceros bicornis" }}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Ear tag number"), {
      target: { value: "NA 1234" },
    });
    expect(onChange).toHaveBeenCalledWith({
      species: "Diceros bicornis",
      ear_tag: "NA 1234",
    });
  });

  it("keeps a value of a field the type lacks under Other, with a remove button", () => {
    const onChange = vi.fn();
    render(
      <EntityFieldInputs
        fields={fields}
        draft={{ licence_plate: "N 123 W" }}
        onChange={onChange}
      />,
    );
    expect(screen.getByText("Other")).toBeInTheDocument();
    expect(screen.getByText("N 123 W")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove licence_plate" }),
    );
    expect(onChange).toHaveBeenCalledWith({ licence_plate: null });
  });

  it("renders nothing for a type without fields and an empty document", () => {
    const { container } = render(
      <EntityFieldInputs fields={[]} draft={{}} onChange={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("EntityDetailsCard", () => {
  it("lists the filled fields and hides the card when nothing can be said", () => {
    const { rerender, container } = render(
      <EntityDetailsCard
        fields={fields}
        attributes={{ vhf_frequency_mhz: 148.32 }}
      />,
    );
    expect(screen.getByText("VHF frequency")).toBeInTheDocument();
    expect(screen.getByText("148.32 MHz")).toBeInTheDocument();
    expect(screen.queryByText("Ear tag number")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit/ }),
    ).not.toBeInTheDocument();
    rerender(<EntityDetailsCard fields={fields} attributes={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("invites a person who may edit to fill the fields in", () => {
    const onEdit = vi.fn();
    render(
      <EntityDetailsCard fields={fields} attributes={{}} onEdit={onEdit} />,
    );
    expect(screen.getByText("Nothing filled in yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
    expect(onEdit).toHaveBeenCalled();
  });
});
