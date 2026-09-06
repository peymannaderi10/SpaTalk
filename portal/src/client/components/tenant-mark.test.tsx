import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TenantMark } from "./tenant-mark";

/**
 * The clinic's mark in the shell: its logo once it has one, and until then
 * the first letter of its name on the primary colour.
 */
describe("the tenant mark", () => {
  it("shows the clinic's initial, upper-cased, when there is no logo", () => {
    render(<TenantMark name="skincentrix" />);
    const mark = screen.getByTestId("tenant-mark");
    expect(mark).toHaveTextContent("S");
    expect(mark.querySelector("img")).toBeNull();
  });

  it("takes the initial from the first word, whatever the spacing", () => {
    render(<TenantMark name="  the glow room" />);
    expect(screen.getByTestId("tenant-mark")).toHaveTextContent("T");
  });

  it("shows the logo, named after the clinic, when there is one", () => {
    render(
      <TenantMark name="Skincentrix" logoUrl="https://cdn.example/logo.png" />,
    );
    const logo = screen.getByRole("img", { name: "Skincentrix" });
    expect(logo).toHaveAttribute("src", "https://cdn.example/logo.png");
    expect(screen.getByTestId("tenant-mark")).not.toHaveTextContent("S");
  });

  it("falls back to the initial when the logo is null, as an unset upload arrives", () => {
    render(<TenantMark name="Skincentrix" logoUrl={null} />);
    expect(screen.getByTestId("tenant-mark")).toHaveTextContent("S");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("still draws a mark for a name it cannot take a letter from", () => {
    render(<TenantMark name="   " />);
    const mark = screen.getByTestId("tenant-mark");
    expect(mark).toHaveTextContent("");
    expect(mark.querySelector("svg")).not.toBeNull();
  });
});
