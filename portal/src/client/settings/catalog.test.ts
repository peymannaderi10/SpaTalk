import { describe, expect, test } from "vitest";
import { SERVICE_ID_MAX, slugifyServiceId, uniqueServiceId } from "./catalog";

describe("slugifyServiceId", () => {
  test("lowercases, keeps letters and digits, joins words with underscores", () => {
    expect(slugifyServiceId("Gold Facial")).toBe("gold_facial");
    expect(slugifyServiceId("  Ultra-Deluxe!! 24k  Gold ")).toBe(
      "ultra_deluxe_24k_gold",
    );
    expect(slugifyServiceId("Café Peel")).toBe("cafe_peel");
  });

  test("is empty for a name with nothing to take", () => {
    expect(slugifyServiceId("")).toBe("");
    expect(slugifyServiceId("  !!  ")).toBe("");
  });

  test("stops at forty characters and never ends on an underscore", () => {
    const id = slugifyServiceId(
      "a very long treatment name that goes on and on and on for ever",
    );
    expect(id.length).toBeLessThanOrEqual(SERVICE_ID_MAX);
    expect(id.endsWith("_")).toBe(false);
    expect(id).toBe("a_very_long_treatment_name_that_goes_on");
  });
});

describe("uniqueServiceId", () => {
  test("is the slug itself when nobody has it", () => {
    expect(uniqueServiceId("Gold Facial", ["peel"])).toBe("gold_facial");
  });

  test("counts up from _2 past every id already taken", () => {
    expect(uniqueServiceId("Gold Facial", ["gold_facial"])).toBe(
      "gold_facial_2",
    );
    expect(
      uniqueServiceId("Gold Facial", ["gold_facial", "gold_facial_2"]),
    ).toBe("gold_facial_3");
  });

  test("makes room for the suffix inside the limit", () => {
    const name = "a very long treatment name that goes on and on and on";
    const base = slugifyServiceId(name);
    expect(base.length).toBe(SERVICE_ID_MAX - 1);
    const second = uniqueServiceId(name, [base]);
    expect(second.length).toBeLessThanOrEqual(SERVICE_ID_MAX);
    expect(second.endsWith("_2")).toBe(true);
    expect(second).not.toContain("__");
  });

  test("is empty, not _2, for a name with nothing to take", () => {
    expect(uniqueServiceId("", ["gold_facial"])).toBe("");
  });
});
