import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  gridColumns,
  overviewTiles,
  OverviewTiles,
  type OverviewCards,
} from "./overview";

/**
 * Who the cards are for.
 *
 * "Estimated cost" is what the providers charged the agency to answer this
 * clinic's phone — the agency's cost of goods, not the clinic's bill. A client
 * pays the list price and nothing on this page should invite them to compare
 * the two, so the card is the agency's to see and nobody else's. It is decided
 * from `viewerIsAgencyAdmin`, which `getTenantOverview` puts in its answer on
 * the server, rather than from anything the browser could be talked into.
 */

const totals = {
  calls: 2,
  call_minutes: 6,
  sms_in: 1,
  sms_out: 3,
  chats: 1,
  est_cost_cad: 1.23,
};

function overview(viewerIsAgencyAdmin: boolean): OverviewCards {
  return {
    viewerIsAgencyAdmin,
    month: { totals },
    health: { open_items: 3, overdue_items: 1 },
    latency: [{ p95_ms: 420 }],
  };
}

function mount(viewerIsAgencyAdmin: boolean) {
  return render(
    <OverviewTiles tiles={overviewTiles(overview(viewerIsAgencyAdmin))} />,
  );
}

describe("the overview cards", () => {
  it("shows the agency what its providers charged, and the reply time", () => {
    mount(true);
    expect(screen.getByTestId("tile-est-cost")).toHaveTextContent("1.23");
    expect(screen.getByTestId("tile-p95-latency")).toHaveTextContent("420 ms");
  });

  it("shows a clinic neither the provider cost nor the reply time", () => {
    mount(false);
    expect(screen.queryByTestId("tile-p95-latency")).toBeNull();
    expect(screen.queryByTestId("tile-est-cost")).toBeNull();
    expect(screen.queryByText("Estimated cost")).toBeNull();
  });

  it("keeps the clinic's own cards for everyone", () => {
    for (const isAdmin of [true, false]) {
      const { unmount } = mount(isAdmin);
      expect(screen.getByTestId("tile-calls")).toHaveTextContent("2");
      expect(screen.getByTestId("tile-call-minutes")).toHaveTextContent("6.0");
      expect(screen.getByTestId("tile-texts")).toHaveTextContent("4");
      expect(screen.getByTestId("tile-chats")).toHaveTextContent("1");
      expect(screen.getByTestId("tile-open-items")).toHaveTextContent("3");
      expect(screen.getByTestId("tile-overdue-items")).toHaveTextContent("1");
      unmount();
    }
  });

  it("counts the cards: six for a clinic, eight for the agency", () => {
    expect(overviewTiles(overview(false))).toHaveLength(6);
    expect(overviewTiles(overview(true))).toHaveLength(8);
  });

  it("says nothing about reply time until there is a day to say it about", () => {
    const tiles = overviewTiles({ ...overview(true), latency: [] });
    const latency = tiles.find((tile) => tile.id === "p95-latency");
    expect(latency?.value).toBe("—");
  });
});

describe("the row of cards", () => {
  it("lays six cards out three and three, and eight four and four", () => {
    expect(gridColumns(6)).toBe(3);
    expect(gridColumns(8)).toBe(4);
    const { unmount } = mount(false);
    expect(screen.getByTestId("overview-tiles").className).toContain(
      "lg:grid-cols-3",
    );
    unmount();
    mount(true);
    expect(screen.getByTestId("overview-tiles").className).toContain(
      "lg:grid-cols-4",
    );
  });
});
