import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeAll, describe, expect, it } from "vitest";
import {
  NAV_SECTIONS,
  PLATFORM_SECTIONS,
  platformSections,
  type NavContext,
} from "../nav";
import { AppLayout } from "./AppLayout";

/**
 * jsdom 27 still ships no `matchMedia`, and `useIsMobile` — which the sidebar
 * uses to decide between the rail and the sheet — asks for one on mount. The
 * stub answers "not mobile", which is the desktop shell these tests are about;
 * the mobile sheet is proved in the browser, in `e2e-tests/tests/shell.spec.ts`.
 */
beforeAll(() => {
  if (typeof window.matchMedia !== "function") {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
});

/**
 * The shell, rendered from props alone.
 *
 * `AppLayout` imports nothing from Wasp — that is what lets it be rendered
 * here at all — so everything it needs arrives as a prop and every assertion
 * below is about what a person with a given role can reach from the sidebar.
 */

const owner: NavContext = {
  orgSlug: "skincentrix",
  role: "OWNER",
  isAdmin: false,
};

const staff: NavContext = { ...owner, role: "STAFF" };
const admin: NavContext = { ...owner, isAdmin: true };

function mount(context: NavContext, extra: Record<string, unknown> = {}) {
  return render(
    <MemoryRouter initialEntries={[`/app/${context.orgSlug}/overview`]}>
      <AppLayout
        context={context}
        breadcrumbs={[{ label: "Skincentrix", to: "/app/skincentrix" }, { label: "Overview" }]}
        orgSwitcher={<div data-testid="org-switcher">Skincentrix</div>}
        profile={{ name: "Ada Lovelace", email: "ada@example.com", onSignOut: () => {} }}
        {...extra}
      >
        <p>the page</p>
      </AppLayout>
    </MemoryRouter>,
  );
}

function itemsOf(title: string) {
  const section = NAV_SECTIONS.find((candidate) => candidate.title === title);
  if (!section) throw new Error(`no section called ${title}`);
  return section.items;
}

/** The agency's own items, which live in the other shell entirely. */
function platformItems() {
  return PLATFORM_SECTIONS.flatMap((section) => section.items);
}

describe("the app shell", () => {
  it("renders every item of every section an owner may see, with its testid", () => {
    mount(owner);

    for (const title of ["Front desk", "Setup", "Account"]) {
      for (const item of itemsOf(title)) {
        const link = screen.getByTestId(item.testId);
        expect(link, `${item.testId} is missing from the sidebar`).toBeTruthy();
        expect(link.getAttribute("href")).toBe(
          item.to.replace(":orgSlug", "skincentrix"),
        );
      }
    }
  });

  it("keeps the platform section out of a business's shell, for an agency admin too", () => {
    // The two shells are separate: a clinic's navigation is about the clinic,
    // whoever is looking at it. An admin's way back is the user menu and the
    // organisation switcher, not a section here.
    for (const context of [owner, staff, admin]) {
      const { unmount } = mount(context);
      for (const item of platformItems()) {
        expect(screen.queryByTestId(item.testId)).toBeNull();
      }
      expect(screen.queryByText("Platform")).toBeNull();
      unmount();
    }
  });

  it("shows the platform section when it is the admin shell being rendered", () => {
    mount(admin, { sections: platformSections(admin) });
    for (const item of platformItems()) {
      expect(screen.getByTestId(item.testId)).toBeTruthy();
    }
  });

  it("keeps billing and people away from a staff member", () => {
    mount(staff);
    expect(screen.queryByTestId("nav-billing")).toBeNull();
    expect(screen.queryByTestId("nav-people")).toBeNull();
    // …while the pages every member may open are still there.
    expect(screen.getByTestId("nav-requests")).toBeTruthy();
  });

  it("marks the item the current route is on, and only that one", () => {
    mount(owner);
    const active = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("data-active") === "true");
    expect(active.map((link) => link.getAttribute("data-testid"))).toEqual([
      "nav-overview",
    ]);
  });

  it("carries the organisation switcher, the header controls and the breadcrumbs", () => {
    mount(owner);
    expect(screen.getByTestId("org-switcher")).toBeTruthy();
    expect(screen.getByTestId("command-palette-open")).toBeTruthy();
    expect(screen.getByTestId("theme-switch")).toBeTruthy();
    expect(screen.getByTestId("profile-menu")).toBeTruthy();
    expect(screen.getByText("Overview", { selector: "[data-slot=breadcrumb-page]" })).toBeTruthy();
  });

  it("puts the content in a container-query context, which the kit's widths need", () => {
    const { container } = mount(owner);
    const inset = container.querySelector("[data-slot=sidebar-inset]");
    expect(inset?.className).toContain("@container/content");
    expect(screen.getByText("the page")).toBeTruthy();
  });

  it("renders only the sections it is given when the caller narrows them", () => {
    mount(admin, { sections: platformSections(admin) });

    for (const item of platformItems()) {
      expect(screen.getByTestId(item.testId)).toBeTruthy();
    }
    for (const item of itemsOf("Front desk")) {
      expect(screen.queryByTestId(item.testId)).toBeNull();
    }
  });
});
