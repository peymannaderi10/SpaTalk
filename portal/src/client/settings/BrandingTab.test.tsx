import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LOGO_TOO_LARGE, LOGO_WRONG_TYPE } from "../../organizations/branding";
import { THEME_PRESETS, type Branding } from "../branding/themes";
import { ACCENT_PROBLEM, BrandingTab } from "./BrandingTab";

/**
 * The Branding page: a logo, a theme preset and an accent colour, saved by
 * the tab's own button through `onSave` — never through the settings draft,
 * because none of it is tenant configuration.
 */

/** A one-pixel PNG, as a browser would read it back. */
const TINY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const unset: Branding = {
  logoDataUrl: null,
  themePreset: null,
  accentHex: null,
};

function fileFrom(dataUrl: string, name: string): File {
  const [head, base64] = dataUrl.split(",");
  const type = head.slice("data:".length, head.indexOf(";"));
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return new File([bytes], name, { type });
}

function mount(
  overrides: Partial<Parameters<typeof BrandingTab>[0]> = {},
): ReturnType<typeof vi.fn> {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(
    <BrandingTab
      name="Skincentrix"
      branding={unset}
      disabled={false}
      onSave={onSave}
      {...overrides}
    />,
  );
  return onSave;
}

function preview() {
  return within(screen.getByTestId("branding-logo-preview"));
}

describe("the Branding tab", () => {
  it("renders the five presets as cards, with the stored one marked", () => {
    mount({ branding: { ...unset, themePreset: "rose" } });
    const cards = screen.getAllByRole("radio");
    expect(cards.map((card) => card.getAttribute("data-testid"))).toEqual(
      THEME_PRESETS.map((preset) => `branding-preset-${preset.id}`),
    );
    expect(cards).toHaveLength(5);
    for (const preset of THEME_PRESETS) {
      expect(screen.getByText(preset.label)).toBeInTheDocument();
    }
    expect(screen.getByTestId("branding-preset-rose")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByTestId("branding-preset-clinic")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("marks clinic when nothing was chosen, since that is the look it wears", () => {
    mount();
    expect(screen.getByTestId("branding-preset-clinic")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("saves the preset that was chosen, by id, and says so", async () => {
    const onSave = mount();
    fireEvent.click(screen.getByTestId("branding-preset-forest"));
    expect(screen.getByTestId("branding-preset-forest")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByTestId("branding-save"));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      logoDataUrl: null,
      themePreset: "forest",
      accentHex: null,
    });
    expect(await screen.findByTestId("branding-saved")).toHaveTextContent(
      "Saved",
    );
  });

  it("shows the error for an accent that is not a colour, and does not save", async () => {
    const onSave = mount();
    const accent = screen.getByTestId("branding-accent");
    fireEvent.change(accent, { target: { value: "#xyz" } });
    fireEvent.click(screen.getByTestId("branding-save"));

    expect(screen.getByTestId("branding-accent-problem")).toHaveTextContent(
      ACCENT_PROBLEM,
    );
    expect(accent).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(onSave).not.toHaveBeenCalled());
    expect(screen.queryByTestId("branding-saved")).toBeNull();
  });

  it("saves a valid accent lowercased, and the reset hands the colour back to the preset", async () => {
    const onSave = mount({ branding: { ...unset, themePreset: "sand" } });
    const accent = screen.getByTestId("branding-accent");
    fireEvent.change(accent, { target: { value: "#1A2B3C" } });
    expect(accent).not.toHaveAttribute("aria-invalid");
    fireEvent.click(screen.getByTestId("branding-save"));
    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith({
        logoDataUrl: null,
        themePreset: "sand",
        accentHex: "#1a2b3c",
      }),
    );

    fireEvent.click(screen.getByTestId("branding-accent-reset"));
    expect(accent).toHaveValue("");
    fireEvent.click(screen.getByTestId("branding-save"));
    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith({
        logoDataUrl: null,
        themePreset: "sand",
        accentHex: null,
      }),
    );
  });

  it("offers the browser's colour picker beside the text, writing the same field", () => {
    mount();
    const picker = screen.getByTestId("branding-accent-picker");
    expect(picker).toHaveAttribute("type", "color");
    fireEvent.change(picker, { target: { value: "#336699" } });
    expect(screen.getByTestId("branding-accent")).toHaveValue("#336699");
  });

  it("takes only a PNG, an SVG or a JPEG, and refuses a file over 200 KB with the message", async () => {
    const onSave = mount();
    const input = screen.getByTestId("branding-logo-file");
    expect(input).toHaveAttribute(
      "accept",
      "image/png,image/svg+xml,image/jpeg",
    );

    const big = new File([new Uint8Array(300 * 1024)], "big.png", {
      type: "image/png",
    });
    fireEvent.change(input, { target: { files: [big] } });
    expect(screen.getByTestId("branding-logo-problem")).toHaveTextContent(
      LOGO_TOO_LARGE,
    );
    expect(screen.getByTestId("branding-logo-problem")).toHaveTextContent(
      "Keep the logo under 200 KB",
    );
    expect(preview().queryByRole("img")).toBeNull();

    const text = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [text] } });
    expect(screen.getByTestId("branding-logo-problem")).toHaveTextContent(
      LOGO_WRONG_TYPE,
    );

    // Nothing refused reaches a save.
    fireEvent.click(screen.getByTestId("branding-save"));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(unset);
  });

  it("previews a small PNG in the mark and saves it as a data URL", async () => {
    const onSave = mount();
    expect(preview().getByTestId("tenant-mark")).toHaveTextContent("S");

    fireEvent.change(screen.getByTestId("branding-logo-file"), {
      target: { files: [fileFrom(TINY_PNG, "logo.png")] },
    });

    const logo = await preview().findByRole("img", { name: "Skincentrix" });
    expect(logo).toHaveAttribute("src", TINY_PNG);
    expect(screen.queryByTestId("branding-logo-problem")).toBeNull();

    fireEvent.click(screen.getByTestId("branding-save"));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        logoDataUrl: TINY_PNG,
        themePreset: null,
        accentHex: null,
      }),
    );
  });

  it("shows the stored logo and removes it on request", async () => {
    const onSave = mount({ branding: { ...unset, logoDataUrl: TINY_PNG } });
    expect(preview().getByRole("img", { name: "Skincentrix" })).toHaveAttribute(
      "src",
      TINY_PNG,
    );

    fireEvent.click(screen.getByTestId("branding-logo-remove"));
    expect(preview().queryByRole("img")).toBeNull();
    expect(preview().getByTestId("tenant-mark")).toHaveTextContent("S");

    fireEvent.click(screen.getByTestId("branding-save"));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(unset));
  });

  it("says what a refused save said", async () => {
    const onSave = vi
      .fn()
      .mockRejectedValue(
        new Error("Only an owner of this organisation can do this."),
      );
    mount({ onSave });
    fireEvent.click(screen.getByTestId("branding-preset-slate"));
    fireEvent.click(screen.getByTestId("branding-save"));

    expect(await screen.findByTestId("branding-problem")).toHaveTextContent(
      "Only an owner of this organisation can do this.",
    );
    expect(screen.queryByTestId("branding-saved")).toBeNull();
  });

  it("is read only for staff: no save, no upload, no choosing", () => {
    mount({ disabled: true, branding: { ...unset, themePreset: "rose" } });
    expect(screen.queryByTestId("branding-save")).toBeNull();
    expect(screen.queryByTestId("branding-accent-reset")).toBeNull();
    expect(screen.getByTestId("branding-logo-file")).toBeDisabled();
    expect(screen.getByTestId("branding-accent")).toBeDisabled();
    for (const card of screen.getAllByRole("radio")) {
      expect(card).toBeDisabled();
    }
    // What is stored still reads.
    expect(screen.getByTestId("branding-preset-rose")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
