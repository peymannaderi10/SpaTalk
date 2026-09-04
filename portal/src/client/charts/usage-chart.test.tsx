import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { UsageChart, type UsagePoint } from "./usage-chart";

/**
 * The chart, rendered from props alone: it imports nothing from Wasp, so the
 * page's operation never has to run for these to pass.
 *
 * Recharts measures its container and draws nothing at zero by zero, which is
 * what jsdom lays every element out at. So `ResizeObserver` is stubbed —
 * Recharts only measures when one exists, the same gap `AppLayout.test.tsx`
 * fills for `matchMedia` — and the responsive container alone is given a box.
 * Only that element: the legend is measured the same way, and a legend as tall
 * as the chart would leave the plot no height at all.
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

const days: UsagePoint[] = [
  { day: "Mon 1", calls: 4, texts: 6, chats: 1 },
  { day: "Tue 2", calls: 7, texts: 2, chats: 3 },
  { day: "Wed 3", calls: 2, texts: 5, chats: 4 },
];

describe("UsageChart", () => {
  it("draws a bar for every day and channel", () => {
    const { container } = render(<UsageChart data={days} />);

    expect(container.querySelector("[data-slot='chart']")).not.toBeNull();
    // Three stacked series over three days, each with something to show.
    expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBe(9);
  });

  it("names every day on the x axis", () => {
    const { container } = render(<UsageChart data={days} />);

    expect(axisTicks(container, "xAxis")).toEqual(days.map((day) => day.day));
  });

  it("names the three channels in the legend", () => {
    render(<UsageChart data={days} />);

    expect(screen.getByText("Calls")).toBeInTheDocument();
    expect(screen.getByText("Texts")).toBeInTheDocument();
    expect(screen.getByText("Chats")).toBeInTheDocument();
  });

  it("paints the series from the chart tokens, not from a literal colour", () => {
    const { container } = render(<UsageChart data={days} />);
    const style = container.querySelector("style");

    expect(style?.textContent).toContain("--color-calls: var(--chart-1)");
    expect(style?.textContent).toContain("--color-texts: var(--chart-2)");
    expect(style?.textContent).toContain("--color-chats: var(--chart-3)");
  });

  it("says so rather than drawing an empty chart when there are no days", () => {
    const { container } = render(<UsageChart data={[]} />);

    expect(screen.getByText("No days recorded yet.")).toBeInTheDocument();
    expect(container.querySelector("[data-slot='chart']")).toBeNull();
  });
});
