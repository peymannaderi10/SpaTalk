import { describe, expect, test } from "vitest";
import { fieldsOf, objectFields, rootFields } from "./schemaFields";

/**
 * A trimmed copy of what `GET /internal/schema/tenant-config` serves: pydantic's
 * own JSON schema. The settings forms are built from it, so the shapes that
 * matter are the ones asserted here.
 */
const schema = {
  $defs: {
    Destination: {
      properties: {
        kind: { enum: ["slack", "email", "webhook"], title: "Kind", type: "string" },
        webhook_env: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Webhook Env",
        },
        urgent_only: { default: false, title: "Urgent Only", type: "boolean" },
      },
      required: ["kind"],
      title: "Destination",
      type: "object",
    },
    Escalation: {
      properties: {
        owner_email: { title: "Owner Email", type: "string" },
        urgent_minutes: { default: 15, title: "Urgent Minutes", type: "integer" },
        holidays_list: { items: { type: "string" }, title: "Holidays", type: "array" },
      },
      required: ["owner_email"],
      title: "Escalation",
      type: "object",
    },
  },
  properties: {
    timezone: { default: "America/Toronto", title: "Timezone", type: "string" },
    retention_days: { default: 30, title: "Retention Days", type: "integer" },
    hours: { title: "Hours", type: "object" },
  },
  required: ["hours"],
  title: "TenantConfig",
  type: "object",
};

describe("fieldsOf", () => {
  test("keeps the order the runtime's model declares", () => {
    expect(fieldsOf(schema, "Destination").map((field) => field.name)).toEqual([
      "kind",
      "webhook_env",
      "urgent_only",
    ]);
  });

  test("reads a Literal as a choice with its options", () => {
    const kind = fieldsOf(schema, "Destination")[0];
    expect(kind.kind).toBe("enum");
    expect(kind.options).toEqual(["slack", "email", "webhook"]);
    expect(kind.required).toBe(true);
  });

  test("reads pydantic's anyOf-with-null as an optional value of the real type", () => {
    const webhookEnv = fieldsOf(schema, "Destination")[1];
    expect(webhookEnv.kind).toBe("string");
    expect(webhookEnv.nullable).toBe(true);
    expect(webhookEnv.required).toBe(false);
  });

  test("distinguishes booleans and integers so the right control is drawn", () => {
    expect(fieldsOf(schema, "Destination")[2].kind).toBe("boolean");
    expect(
      fieldsOf(schema, "Escalation").find((f) => f.name === "urgent_minutes")
        ?.kind,
    ).toBe("integer");
  });

  test("marks a shape it has no control for rather than guessing one", () => {
    expect(
      fieldsOf(schema, "Escalation").find((f) => f.name === "holidays_list")
        ?.kind,
    ).toBe("unsupported");
  });

  test("is empty for a model the runtime does not define", () => {
    expect(fieldsOf(schema, "NoSuchModel")).toEqual([]);
    expect(objectFields(undefined)).toEqual([]);
  });
});

describe("rootFields", () => {
  test("returns the named top-level fields, in the order asked for", () => {
    expect(
      rootFields(schema, ["retention_days", "timezone"]).map((f) => f.name),
    ).toEqual(["retention_days", "timezone"]);
  });

  test("drops a field the runtime's schema does not have", () => {
    expect(rootFields(schema, ["timezone", "invented"]).map((f) => f.name)).toEqual([
      "timezone",
    ]);
  });

  test("carries the title the model gave the field", () => {
    expect(rootFields(schema, ["timezone"])[0].title).toBe("Timezone");
  });
});
