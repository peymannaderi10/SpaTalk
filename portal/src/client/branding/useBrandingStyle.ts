import { useEffect, useMemo, useState, type CSSProperties } from "react";

import { resolveTheme, themeChosen, type Branding } from "./themes";

/**
 * The inline style the clinic shell puts on its root element: the tokens of
 * the clinic's preset, resolved for the mode the viewer is in, with the accent
 * over the primary. `undefined` when the organisation has no branding, so a
 * clinic that never chose anything gets the kit's own `Main.css` tokens and
 * nothing inline — and so the admin shell, which passes nothing, is untouched.
 *
 * The mode is the kit's: `useColorMode` puts `.dark` on the body, and this
 * watches that class rather than keeping a second copy of the setting, so a
 * toggle anywhere re-resolves the tokens here.
 */
export function useBrandingStyle(
  branding: Pick<Branding, "themePreset" | "accentHex"> | null | undefined,
): CSSProperties | undefined {
  const dark = useDarkClass();
  const themePreset = branding?.themePreset ?? null;
  const accentHex = branding?.accentHex ?? null;

  return useMemo(() => {
    if (!themeChosen({ themePreset, accentHex })) {
      return undefined;
    }
    return resolveTheme(
      themePreset,
      accentHex,
      dark ? "dark" : "light",
    ) as CSSProperties;
  }, [themePreset, accentHex, dark]);
}

function bodyIsDark(): boolean {
  return (
    typeof document !== "undefined" && document.body.classList.contains("dark")
  );
}

/** Whether the body carries the kit's `.dark` class, kept current as it changes. */
function useDarkClass(): boolean {
  const [dark, setDark] = useState(bodyIsDark);

  useEffect(() => {
    setDark(bodyIsDark());
    const observer = new MutationObserver(() => setDark(bodyIsDark()));
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return dark;
}
