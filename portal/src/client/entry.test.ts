import { describe, expect, it } from "vitest";
import {
  entryDestination,
  orgHomePath,
  PLATFORM_HOME,
  type EntryDestination,
} from "./entry";

/**
 * `/app` is where signing in lands, and it is no longer a page: it decides
 * where this person's work actually is. The decision is this pure function so
 * it can be read, and argued with, without a browser.
 */

const one = [{ slug: "skincentrix" }];
const two = [{ slug: "skincentrix" }, { slug: "glow-mississauga" }];

describe("where signing in lands", () => {
  it("sends an agency admin to the platform", () => {
    expect(
      entryDestination({ isAdmin: true, organizations: [] }),
    ).toEqual<EntryDestination>({ kind: "redirect", to: PLATFORM_HOME });
  });

  it("sends an agency admin to the platform even when they belong to one organisation", () => {
    // An admin is added to organisations all the time — it is how they see a
    // client's pages. Their own dashboard is still the platform's.
    expect(entryDestination({ isAdmin: true, organizations: one })).toEqual({
      kind: "redirect",
      to: PLATFORM_HOME,
    });
    expect(entryDestination({ isAdmin: true, organizations: two })).toEqual({
      kind: "redirect",
      to: PLATFORM_HOME,
    });
  });

  it("sends a person with one organisation straight into it", () => {
    expect(entryDestination({ isAdmin: false, organizations: one })).toEqual({
      kind: "redirect",
      to: "/app/skincentrix",
    });
  });

  it("has nowhere to send a person who belongs to no organisation", () => {
    expect(entryDestination({ isAdmin: false, organizations: [] })).toEqual({
      kind: "none",
    });
  });

  it("asks a person who belongs to several which one they meant", () => {
    expect(entryDestination({ isAdmin: false, organizations: two })).toEqual({
      kind: "choose",
    });
  });

  it("escapes a slug on its way into the path", () => {
    expect(orgHomePath("skincentrix")).toBe("/app/skincentrix");
    expect(orgHomePath("a b")).toBe("/app/a%20b");
    expect(
      entryDestination({ isAdmin: false, organizations: [{ slug: "a b" }] }),
    ).toEqual({ kind: "redirect", to: "/app/a%20b" });
  });
});
