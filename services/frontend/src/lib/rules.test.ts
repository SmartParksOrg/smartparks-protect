import { describe, expect, it } from "vitest";

import { documentToForm, formToDocument } from "@/lib/rules";

const SPEEDING = {
  trigger: { kind: "position" },
  conditions: { type: "threshold", metric: "speed_kmh", op: ">", value: 60 },
  cooldown_seconds: 600,
  scope: { entity_type_ids: ["11111111-1111-1111-1111-111111111111"] },
  event: {
    event_type: "SPEED_LIMIT_VIOLATION",
    severity: "warning",
    title: "{entity} at {value} km/h",
    create_alert: true,
  },
};

describe("the rule form's scope by entity type (phase 37)", () => {
  it("round-trips a document scoped to a type", () => {
    const form = documentToForm(SPEEDING);
    expect(form).not.toBeNull();
    expect(form!.entity_type_ids).toEqual([
      "11111111-1111-1111-1111-111111111111",
    ]);
    expect(form!.entity_ids).toEqual([]);
    const doc = formToDocument(form!);
    expect(doc.scope).toEqual({
      entity_type_ids: ["11111111-1111-1111-1111-111111111111"],
    });
    expect(doc.cooldown_seconds).toBe(600);
  });

  it("writes no scope when nothing is chosen and still hands a device scope to JSON", () => {
    const form = documentToForm({ ...SPEEDING, scope: {} });
    expect(formToDocument(form!).scope).toBeUndefined();
    expect(documentToForm({ ...SPEEDING, scope: { device_ids: ["x"] } })).toBeNull();
  });
});
