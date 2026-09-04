import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { RevenueChart, type RevenuePoint } from "./revenue-chart";

/**
 * The same conditions as `usage-chart.test.tsx`: props only, no Wasp, and a
 * measurable responsive container so Recharts draws something.
 */
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof globalThis.ResizeObserver;

  const measure = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function (this: Element) {
    if (!this.classList.contains("recharts-responsive-container")) {
      return measure.call(this);
    }
    return {
      width: 640,
      height: 320,
      top: 0,
      left: 0,
      right: 640,
      bottom: 320,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
});

/**
 * The axis labels Recharts drew, in order. A tick that does not fit on one
 * line becomes several `tspan`s, so they are joined back with the space that
 * split them.
 */
function axisTicks(container: HTMLElement, axis: "xAxis" | "yAxis"): string[] {
  return Array.from(
    container.querySelectorAll(
      `.recharts-${axis}-tick-labels .recharts-cartesian-axis-tick-value`,
    ),
  ).map((tick) =>
    Array.from(tick.querySelectorAll("tspan"))
      .map((span) => span.textContent ?? "")
      .join(" ")
      .trim(),
  );
}

const days: RevenuePoint[] = [
  { day: "Mon 1", revenue: 120, profit: 40 },
  { day: "Tue 2", revenue: 300, profit: 90 },
  { day: "Wed 3", revenue: 80, profit: 10 },
];

describe("RevenueChart", () => {
  it("draws an area for each of the two series", () => {
    const { container } = render(<RevenueChart data={days} />);

    expect(container.querySelector("[data-slot='chart']")).not.toBeNull();
    expect(container.querySelectorAll(".recharts-area").length).toBe(2);
  });

  it("names every day on the x axis", () => {
    const { container } = render(<RevenueChart data={days} />);

    expect(axisTicks(container, "xAxis")).toEqual(days.map((day) => day.day));
  });

  it("puts money on the y axis in dollars", () => {
    const { container } = render(<RevenueChart data={days} />);

    for (const tick of axisTicks(container, "yAxis")) {
      expect(tick).toMatch(/^\$[\d,]+\.\d{2}$/);
    }
  });

  it("names both series in the legend", () => {
    render(<RevenueChart data={days} />);

    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Profit")).toBeInTheDocument();
  });

  it("paints the series from the chart tokens, not from a literal colour", () => {
    const { container } = render(<RevenueChart data={days} />);
    const style = container.querySelector("style");

    expect(style?.textContent).toContain("--color-revenue: var(--chart-1)");
    expect(style?.textContent).toContain("--color-profit: var(--chart-2)");
  });

  it("says so rather than drawing an empty chart when no day was recorded", () => {
    const { container } = render(<RevenueChart data={[]} />);

    expect(screen.getByText("No day has been recorded yet.")).toBeInTheDocument();
    expect(container.querySelector("[data-slot='chart']")).toBeNull();
  });
});
