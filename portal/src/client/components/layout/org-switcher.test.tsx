import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { SidebarProvider } from "../ui/sidebar";
import { OrgSwitcher, type SwitchableOrg } from "./org-switcher";

/**
 * The top of the clinic's sidebar: the clinic's mark and its name, and
 * nothing under them. The word "Organisation" used to sit under the name as a
 * subtext; it is gone, and stays gone.
 *
 * jsdom ships no `matchMedia`, and the sidebar's `useIsMobile` asks for one on
 * mount; the stub answers "not mobile", as `AppLayout.test.tsx` does.
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

const skincentrix: SwitchableOrg = {
  id: "org_1",
  name: "Skincentrix",
  slug: "skincentrix",
};
const glow: SwitchableOrg = {
  id: "org_2",
  name: "The Glow Room",
  slug: "glow",
};

function mount(orgs: SwitchableOrg[], currentSlug: string) {
  render(
    <MemoryRouter>
      <SidebarProvider>
        <OrgSwitcher orgs={orgs} currentSlug={currentSlug} onSelect={vi.fn()} />
      </SidebarProvider>
    </MemoryRouter>,
  );
  return screen.getByTestId("org-switcher");
}

describe("the organisation switcher's header", () => {
  it("shows the clinic's mark and its name, and nothing under it", () => {
    const trigger = mount([skincentrix], "skincentrix");
    expect(within(trigger).getByTestId("tenant-mark")).toHaveTextContent("S");
    expect(trigger).toHaveTextContent("Skincentrix");
    expect(screen.queryByText("Organisation")).toBeNull();
    expect(screen.queryByText("Switch organisation")).toBeNull();
  });

  it("says nothing under the name with several organisations either", () => {
    const trigger = mount([skincentrix, glow], "glow");
    expect(within(trigger).getByTestId("tenant-mark")).toHaveTextContent("T");
    expect(trigger).toHaveTextContent("The Glow Room");
    expect(screen.queryByText("Switch organisation")).toBeNull();
    expect(screen.queryByText("Organisation")).toBeNull();
  });

  it("keeps the accessible name the browser suite selects it by", () => {
    // `e2e-tests/tests/qa-gate-b.spec.ts` finds the trigger with
    // getByLabel("Organisation"); a label is not text under the name.
    const trigger = mount([skincentrix], "skincentrix");
    expect(trigger).toHaveAttribute("aria-label", "Organisation");
  });

  it("shows the slug, marked, while the organisations are still loading", () => {
    const trigger = mount([], "skincentrix");
    expect(trigger).toHaveTextContent("skincentrix");
    expect(within(trigger).getByTestId("tenant-mark")).toHaveTextContent("S");
  });
});
