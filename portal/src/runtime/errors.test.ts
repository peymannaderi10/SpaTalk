import { describe, expect, test } from "vitest";
import {
  fieldErrorsFrom,
  friendlyRuntimeMessage,
  summariseFieldErrors,
} from "./errors";

describe("fieldErrorsFrom", () => {
  test("names the configuration field the runtime refused", () => {
    const errors = fieldErrorsFrom({
      detail: [
        {
          loc: ["config", "hours"],
          msg: "Value error, bad hours for mon: 23:00-19:00",
          type: "value_error",
        },
      ],
    });

    expect(errors).toHaveLength(1);
    expect(errors[0].field).toBe("hours");
    expect(errors[0].path).toEqual(["hours"]);
    expect(errors[0].message).toContain("bad hours for mon");
  });

  test("keeps the rest of the path so a form can find the entry", () => {
    const [error] = fieldErrorsFrom({
      detail: [{ loc: ["config", "services", 2, "booking_url"], msg: "required" }],
    });

    expect(error.field).toBe("services");
    expect(error.path).toEqual(["services", "2", "booking_url"]);
  });

  test("drops the request body's own name, not a field called config", () => {
    const [error] = fieldErrorsFrom({
      detail: [{ loc: ["body", "bundle"], msg: "invalid bundle" }],
    });
    expect(error.path).toEqual(["bundle"]);
  });

  test("is empty for anything that is not a pydantic refusal", () => {
    expect(fieldErrorsFrom(null)).toEqual([]);
    expect(fieldErrorsFrom({ detail: "invalid internal key" })).toEqual([]);
    expect(fieldErrorsFrom({ detail: [{ msg: "no loc" }] })).toEqual([]);
  });
});

describe("summariseFieldErrors", () => {
  test("reads as one sentence naming each field", () => {
    expect(
      summariseFieldErrors([
        { path: ["hours"], field: "hours", message: "bad hours" },
        { path: ["scripts", "clinical"], field: "scripts", message: "needs 911" },
      ]),
    ).toBe("hours: bad hours; scripts → clinical: needs 911");
  });
});

describe("friendlyRuntimeMessage", () => {
  test("never turns our own key problem into the person's problem", () => {
    const message = friendlyRuntimeMessage(401, "usage");
    expect(message).not.toContain("key");
    expect(message).toContain("usage");
  });

  test("says the service is not answering when nothing answered at all", () => {
    expect(friendlyRuntimeMessage(null, "usage")).toContain("not answering");
  });
});
