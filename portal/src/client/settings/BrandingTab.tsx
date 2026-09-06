import { IconCheck, IconTrash } from "@tabler/icons-react";
import { useEffect, useState, type ChangeEvent } from "react";

import {
  LOGO_MAX_BYTES,
  LOGO_MIME_TYPES,
  LOGO_TOO_LARGE,
  LOGO_WRONG_TYPE,
} from "../../organizations/branding";
import {
  contrastForeground,
  DEFAULT_PRESET,
  isHex,
  THEME_PRESETS,
  type Branding,
} from "../branding/themes";
import { TenantMark } from "../components/tenant-mark";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { cn } from "../utils";

/**
 * The Branding page: the logo, the theme and the accent colour a clinic's own
 * dashboard wears.
 *
 * Unlike every other Setup section, none of this is tenant configuration.
 * The runtime never sees a logo or a colour: the three fields live on the
 * portal's `Organization` row, are saved by `updateOrganizationBranding`
 * through this tab's own Save, and are kept out of the settings draft and its
 * versions on purpose — a branding change writes no config version, and a
 * rollback does not undo one. `SettingsPage` therefore hands this tab the
 * organisation, not the draft, and hides its own save button while it is
 * open.
 *
 * The sections follow the other tabs' sub-section idiom (an `h3` and a muted
 * line), the preset cards are the kit's outlined-when-selected pattern, and
 * the mark is the same `TenantMark` the sidebar draws, so the preview is the
 * thing itself.
 */

export const ACCENT_PROBLEM = "Use a colour like #1a2b3c";
const LOGO_UNREADABLE = "That file could not be read.";

export function BrandingTab({
  name,
  branding,
  disabled,
  onSave,
}: {
  /** The clinic's name, for the mark's initial until there is a logo. */
  name: string;
  /** What is stored now. */
  branding: Branding;
  /** Staff read; only an owner saves, and the server enforces it. */
  disabled: boolean;
  onSave: (next: Branding) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Branding>(branding);
  const [accentText, setAccentText] = useState(branding.accentHex ?? "");
  const [logoProblem, setLogoProblem] = useState<string | null>(null);
  const [accentProblem, setAccentProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // What is stored changed under the page — a save came back through the
  // organisation query, or another owner's did — so the page shows it.
  useEffect(() => {
    setDraft({
      logoDataUrl: branding.logoDataUrl,
      themePreset: branding.themePreset,
      accentHex: branding.accentHex,
    });
    setAccentText(branding.accentHex ?? "");
  }, [branding.logoDataUrl, branding.themePreset, branding.accentHex]);

  const selectedPreset = draft.themePreset ?? DEFAULT_PRESET;
  const locked = disabled || busy;

  function touched() {
    setSaved(false);
    setProblem(null);
  }

  function chooseLogo(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) {
      return;
    }
    touched();
    setLogoProblem(null);
    // Cleared so the same file can be chosen again after a refusal.
    input.value = "";

    if (!LOGO_MIME_TYPES.includes(file.type)) {
      setLogoProblem(LOGO_WRONG_TYPE);
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      setLogoProblem(LOGO_TOO_LARGE);
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === "string") {
        setDraft((current) => ({ ...current, logoDataUrl: result }));
      } else {
        setLogoProblem(LOGO_UNREADABLE);
      }
    };
    reader.onerror = () => setLogoProblem(LOGO_UNREADABLE);
    reader.readAsDataURL(file);
  }

  function setAccent(value: string) {
    touched();
    setAccentProblem(null);
    setAccentText(value);
  }

  async function save() {
    touched();
    setAccentProblem(null);

    const accent = accentText.trim();
    if (accent !== "" && !isHex(accent)) {
      setAccentProblem(ACCENT_PROBLEM);
      return;
    }
    const next: Branding = {
      logoDataUrl: draft.logoDataUrl,
      themePreset: draft.themePreset,
      accentHex: accent === "" ? null : accent.toLowerCase(),
    };

    setBusy(true);
    try {
      await onSave(next);
      setDraft(next);
      setAccentText(next.accentHex ?? "");
      setSaved(true);
    } catch (caught) {
      setProblem(
        (caught as { message?: string }).message ??
          "The branding could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8" data-testid="branding-tab">
      <p className="text-muted-foreground text-sm">
        How this clinic's dashboard looks, for everyone who opens it. This is
        the portal's own record, not part of the assistant's settings: saving
        here writes no settings version, and rolling one back leaves it alone.
      </p>

      {saved && (
        <Alert data-testid="branding-saved">
          <AlertTitle>Saved</AlertTitle>
          <AlertDescription>
            The dashboard wears it from now on.
          </AlertDescription>
        </Alert>
      )}

      {problem && (
        <Alert variant="destructive" data-testid="branding-problem">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">Logo</h3>
          <p className="text-muted-foreground text-sm">
            Shown at the top of the sidebar in place of the initial. A PNG, SVG
            or JPEG under 200 KB; a square one reads best.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div data-testid="branding-logo-preview">
            <TenantMark
              name={name}
              logoUrl={draft.logoDataUrl}
              className="size-16 rounded-xl"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="branding-logo-file" className="sr-only">
              Logo file
            </Label>
            <Input
              id="branding-logo-file"
              type="file"
              accept={LOGO_MIME_TYPES.join(",")}
              data-testid="branding-logo-file"
              disabled={locked}
              onChange={chooseLogo}
              className="max-w-xs"
            />
            {draft.logoDataUrl && !disabled && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="branding-logo-remove"
                disabled={busy}
                onClick={() => {
                  touched();
                  setLogoProblem(null);
                  setDraft((current) => ({ ...current, logoDataUrl: null }));
                }}
              >
                <IconTrash className="size-4" />
                Remove the logo
              </Button>
            )}
          </div>
        </div>
        {logoProblem && (
          <p
            className="text-destructive text-sm"
            data-testid="branding-logo-problem"
            role="alert"
          >
            {logoProblem}
          </p>
        )}
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">Theme</h3>
          <p className="text-muted-foreground text-sm">
            The colours of the whole dashboard, in light and dark. Clinic is the
            look every clinic starts with.
          </p>
        </div>
        <div
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
          role="radiogroup"
          aria-label="Theme"
        >
          {THEME_PRESETS.map((preset) => {
            const selected = preset.id === selectedPreset;
            return (
              <button
                key={preset.id}
                type="button"
                role="radio"
                aria-checked={selected}
                data-testid={`branding-preset-${preset.id}`}
                disabled={locked}
                onClick={() => {
                  touched();
                  setDraft((current) => ({
                    ...current,
                    themePreset: preset.id,
                  }));
                }}
                className={cn(
                  "bg-card flex items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  selected
                    ? "border-primary ring-primary ring-2"
                    : "hover:bg-accent",
                )}
              >
                <span className="flex shrink-0 gap-1" aria-hidden="true">
                  <span
                    className="size-6 rounded-full border"
                    style={{ background: preset.light["--primary"] }}
                  />
                  <span
                    className="size-6 rounded-full border"
                    style={{ background: preset.light["--background"] }}
                  />
                  <span
                    className="size-6 rounded-full border"
                    style={{ background: preset.light["--accent"] }}
                  />
                </span>
                <span className="flex-1 text-sm font-medium">
                  {preset.label}
                </span>
                {selected && (
                  <IconCheck className="size-4 shrink-0" aria-hidden="true" />
                )}
              </button>
            );
          })}
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">Accent</h3>
          <p className="text-muted-foreground text-sm">
            One colour over the theme's own: buttons, the current item, the
            focus ring. Leave it empty to keep the theme's.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor="branding-accent" className="sr-only">
            Accent colour
          </Label>
          <Input
            id="branding-accent"
            data-testid="branding-accent"
            value={accentText}
            placeholder="#1a2b3c"
            maxLength={7}
            spellCheck={false}
            className="w-32 font-mono"
            aria-invalid={accentProblem ? true : undefined}
            disabled={locked}
            onChange={(event) => setAccent(event.target.value)}
          />
          <input
            type="color"
            data-testid="branding-accent-picker"
            aria-label="Pick the accent colour"
            value={isHex(accentText) ? accentText.toLowerCase() : "#000000"}
            disabled={locked}
            onChange={(event) => setAccent(event.target.value)}
            className="border-input size-9 cursor-pointer rounded-md border bg-transparent p-0.5 disabled:cursor-not-allowed disabled:opacity-50"
          />
          {isHex(accentText) && (
            <span
              className="rounded-md px-2 py-1 text-xs font-medium"
              data-testid="branding-accent-sample"
              style={{
                background: accentText,
                color: contrastForeground(accentText),
              }}
            >
              Aa
            </span>
          )}
          {!disabled && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="branding-accent-reset"
              disabled={busy || accentText === ""}
              onClick={() => setAccent("")}
            >
              Use the preset's colour
            </Button>
          )}
        </div>
        {accentProblem && (
          <p
            className="text-destructive text-sm"
            data-testid="branding-accent-problem"
            role="alert"
          >
            {accentProblem}
          </p>
        )}
      </section>

      {!disabled && (
        <Button
          type="button"
          data-testid="branding-save"
          disabled={busy}
          onClick={save}
        >
          Save branding
        </Button>
      )}
    </div>
  );
}
