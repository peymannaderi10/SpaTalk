import { describe, expect, test } from "vitest";
import {
  BUNDLE_SLOTS,
  emptyBundle,
  isCompleteBundle,
  missingSlots,
  slotForFilename,
  type BundleDraft,
} from "./bundle";

/**
 * The five files a tenant bundle is made of, as the onboarding wizard handles
 * them. The portal never reads what is inside one: it decides which upload is
 * which file and hands all five to the runtime, whose loader is the only thing
 * that understands a bundle (`docs/reference/tenant-config.md`).
 */

describe("BUNDLE_SLOTS", () => {
  test("is exactly the five files the bundle reference names", () => {
    expect(BUNDLE_SLOTS.map((slot) => slot.filename)).toEqual([
      "tenant.yaml",
      "services.yaml",
      "knowledge.md",
      "scripts.yaml",
      "guard.yaml",
    ]);
  });
});

describe("slotForFilename", () => {
  test("recognises each bundle file by its name", () => {
    expect(slotForFilename("tenant.yaml")).toBe("tenant");
    expect(slotForFilename("services.yaml")).toBe("services");
    expect(slotForFilename("knowledge.md")).toBe("knowledge");
    expect(slotForFilename("scripts.yaml")).toBe("scripts");
    expect(slotForFilename("guard.yaml")).toBe("guard");
  });

  test("ignores the directory a file was dragged from, and its casing", () => {
    expect(slotForFilename("tenants/skincentrix/Scripts.YAML")).toBe("scripts");
    expect(slotForFilename("C:\\bundles\\guard.yaml")).toBe("guard");
  });

  test("accepts the .yml spelling of a .yaml file", () => {
    expect(slotForFilename("services.yml")).toBe("services");
  });

  test("refuses a file that is not part of a bundle rather than guessing", () => {
    expect(slotForFilename("notes.txt")).toBeNull();
    expect(slotForFilename("tenant-backup.zip")).toBeNull();
  });
});

describe("missingSlots", () => {
  const full: BundleDraft = {
    tenant: "id: skincentrix",
    services: "services: []",
    knowledge: "# Knowledge",
    scripts: "disclosure: hello",
    guard: "clinical: []",
  };

  test("names nothing when all five files are there", () => {
    expect(missingSlots(full)).toEqual([]);
    expect(isCompleteBundle(full)).toBe(true);
  });

  test("names every file that is still missing", () => {
    expect(missingSlots({ ...emptyBundle(), tenant: "id: x" })).toEqual([
      "services",
      "knowledge",
      "scripts",
      "guard",
    ]);
    expect(isCompleteBundle(emptyBundle())).toBe(false);
  });

  test("treats a file that is only whitespace as missing", () => {
    expect(missingSlots({ ...full, guard: "   \n" })).toEqual(["guard"]);
  });
});
