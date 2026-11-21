import { describe, expect, it } from "vitest";

import type { EntityField } from "@/api/types";
import {
  fieldLabel,
  fieldValueText,
  keyOf,
  numericFields,
  searchText,
  splitAttributes,
  toAttributes,
  toDefinitions,
  toDraft,
} from "./entityFields";

const field = (more: Partial<EntityField> & { key: string }): EntityField => ({
  label: more.key,
  kind: "text",
  choices: [],
  panel: false,
  search: false,
  origin: "standard",
  inherited: false,
  ...more,
});

const vhf = field({ key: "vhf_frequency_mhz", kind: "number", unit: "MHz" });
const sex = field({
  key: "sex",
  label: "Sex",
  kind: "choice",
  choices: [{ value: "female", label: "Female" }],
});
const plate = field({ key: "licence_plate" });
const year = field({ key: "birth_year", kind: "integer" });
const nl = (text: string) =>
  ({ Sex: "Geslacht", Female: "Vrouwtje" })[text] ?? text;

describe("splitAttributes", () => {
  it("gives the filled fields in the order of the form and the rest as other", () => {
    const { filled, other } = splitAttributes([vhf, sex, plate], {
      sex: "female",
      species: "Diceros bicornis",
      vhf_frequency_mhz: 148.32,
      licence_plate: " ",
      old: null,
    });
    expect(filled.map((f) => f.field.key)).toEqual([
      "vhf_frequency_mhz",
      "sex",
    ]);
    expect(other).toEqual([{ key: "species", value: "Diceros bicornis" }]);
  });
  it("takes an entity without a document", () => {
    expect(splitAttributes([vhf], null)).toEqual({ filled: [], other: [] });
  });
});

describe("the texts of a field", () => {
  it("translates a standard field and leaves an own one as typed", () => {
    expect(fieldLabel(sex, nl)).toBe("Geslacht");
    expect(fieldLabel({ ...sex, origin: "own" }, nl)).toBe("Sex");
    expect(fieldValueText(sex, "female", nl)).toBe("Vrouwtje");
  });
  it("shows a number with its unit, a yes or no in words, an unknown choice as stored", () => {
    expect(fieldValueText(vhf, 148.32, nl)).toBe("148.32 MHz");
    expect(
      fieldValueText(field({ key: "tame", kind: "boolean" }), false, nl),
    ).toBe("No");
    expect(fieldValueText(sex, "bull", nl)).toBe("bull");
  });
});

describe("searchText", () => {
  it("gives the values of the fields marked for the search", () => {
    const fields = [{ ...plate, search: true }, vhf, sex];
    expect(
      searchText(fields, {
        licence_plate: "N 123 W",
        sex: "female",
        vhf_frequency_mhz: 148,
      }),
    ).toBe("N 123 W");
    expect(searchText(fields, null)).toBe("");
  });
});

describe("numericFields", () => {
  it("gives the number fields of every type, each key once", () => {
    const type = (fields: EntityField[]) => ({ fields }) as never;
    expect(
      numericFields([type([sex, vhf, year]), type([vhf, plate])]).map(
        (f) => f.key,
      ),
    ).toEqual(["vhf_frequency_mhz", "birth_year"]);
    expect(numericFields(undefined)).toEqual([]);
  });
});

describe("toAttributes", () => {
  it("sends numbers as numbers, a comma as the decimal mark, and leaves empty values out", () => {
    const { attributes, invalid } = toAttributes([vhf, year, plate], {
      vhf_frequency_mhz: " 148,32 ",
      birth_year: "2015",
      licence_plate: " N 123 W ",
      species: "Diceros bicornis",
      removed: null,
      breed: "",
    });
    expect(invalid).toBeNull();
    expect(attributes).toEqual({
      vhf_frequency_mhz: 148.32,
      birth_year: 2015,
      licence_plate: "N 123 W",
      species: "Diceros bicornis",
    });
  });
  it("names the number field whose text is no number", () => {
    expect(
      toAttributes([vhf], { vhf_frequency_mhz: "about 148" }).invalid,
    ).toBe(vhf);
  });
  it("keeps a stored number as it is", () => {
    expect(
      toAttributes([vhf], { vhf_frequency_mhz: 148.32 }).attributes,
    ).toEqual({
      vhf_frequency_mhz: 148.32,
    });
  });
});

describe("the admin's own fields", () => {
  it("makes a key from a label", () => {
    expect(keyOf("Collar colour")).toBe("collar_colour");
    expect(keyOf("  Café 2 ")).toBe("cafe_2");
    expect(keyOf("2nd tag")).toBe("f_2nd_tag");
    expect(keyOf("!!!")).toBe("");
  });
  it("keeps a stored field's key and a choice's value under a new label", () => {
    const stored = field({
      key: "herd",
      label: "Herd",
      kind: "choice",
      origin: "own",
      choices: [{ value: "north", label: "North" }],
    });
    const draft = {
      ...toDraft(stored),
      label: "Herd name",
      choices: "North, South west",
    };
    expect(toDefinitions([draft])).toEqual([
      {
        key: "herd",
        label: "Herd name",
        kind: "choice",
        choices: [
          { value: "north", label: "North" },
          { value: "south_west", label: "South west" },
        ],
        panel: false,
        search: false,
      },
    ]);
  });
  it("gives a new field its key, a unit to a number alone, the search to text alone", () => {
    const base = {
      key: "",
      unit: "cm",
      choices: "",
      panel: true,
      search: true,
    };
    expect(
      toDefinitions([
        { ...base, label: "Horn length", kind: "number" },
        { ...base, label: "Nickname", kind: "text" },
      ]),
    ).toEqual([
      {
        key: "horn_length",
        label: "Horn length",
        kind: "number",
        unit: "cm",
        panel: true,
        search: false,
      },
      {
        key: "nickname",
        label: "Nickname",
        kind: "text",
        panel: true,
        search: true,
      },
    ]);
  });
});
