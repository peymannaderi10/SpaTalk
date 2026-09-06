import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import {
  blockSmsNumber,
  getTenantSettings,
  rollBackTenantConfig,
  saveTenantConfig,
  unblockSmsNumber,
  updateOrganizationBranding,
  useQuery,
} from "wasp/client/operations";
import { Alert, AlertDescription, AlertTitle } from "./components/ui/alert";
import { Button } from "./components/ui/button";
import { Separator } from "./components/ui/separator";
import { SETTINGS_TABS, type SettingsTab } from "./nav";
import { OrgShell, Problem, type Org } from "./OrgShell";
import { BrandingTab } from "./settings/BrandingTab";
import { ContentSection } from "./settings/ContentSection";
import { DeliveryTab } from "./settings/DeliveryTab";
import { HoursTab } from "./settings/HoursTab";
import { IntegrationsTab } from "./settings/Integrations";
import { KnowledgeTab } from "./settings/KnowledgeTab";
import { NumbersTab } from "./settings/NumbersTab";
import { type Draft } from "./settings/schemaFields";
import { ScriptsTab } from "./settings/ScriptsTab";
import { ServicesTab } from "./settings/ServicesTab";
import { SettingsNav } from "./settings/SettingsNav";
import { TeamTab } from "./settings/TeamTab";
import { VersionsPanel } from "./settings/VersionsPanel";

/**
 * The tenant's configuration, edited through forms built from the runtime's own
 * pydantic schema. A save sends the whole configuration and the runtime stores
 * it as the next version; a refusal comes back with the field that was wrong.
 *
 * Only an owner may save or roll back, and that is enforced by the server
 * operations, not by hiding the button.
 *
 * One section is not configuration at all: Branding edits the organisation's
 * own look, stored on the portal's `Organization` row and saved by its own
 * operation. It takes the organisation rather than the draft, has its own
 * save, and the page's save button and version notice step aside while it is
 * open, so a logo or a colour never rides along into a config version.
 *
 * The page is the kit's settings layout (`src/features/settings/index.tsx` in
 * `satnaing/shadcn-admin`): a title, a rule, a side navigation of sections,
 * and the section itself scrolling beside it.
 */

type FieldError = { path: string[]; field: string; message: string };

/**
 * The sections, their order and their icons are `nav.ts`'s `SETTINGS_TABS`,
 * spelled once for the page, its sub-navigation and the URL.
 */
type Tab = SettingsTab;

/** What each section is, in the words the kit's section header wants. */
const SECTIONS: Record<Tab, { description: string }> = {
  Hours: {
    description:
      "When the clinic is open, in its own timezone. Every promised time is counted from these spans.",
  },
  Services: {
    description:
      "The catalog. Only a service on this list can be named, quoted or linked to.",
  },
  Team: {
    description:
      "Who a caller may ask for by name, and which treatments each person performs.",
  },
  Knowledge: {
    description:
      "The prose the assistant may answer from, and the questions it answers in its own words.",
  },
  Scripts: {
    description:
      "The fixed wording. Every sentence the system can say that a model did not write.",
  },
  Delivery: {
    description:
      "Where a tracked request goes, who owns it, and how long the team has.",
  },
  Numbers: {
    description:
      "The numbers mapped to this tenant, and the ones it will not answer.",
  },
  Integrations: {
    description: "Instagram and the clinic's Facebook Page.",
  },
  Branding: {
    description:
      "How this clinic's dashboard looks: its logo, a theme and an accent colour.",
  },
  Versions: {
    description:
      "Every save is a version. Rolling back adds a new one; nothing is removed.",
  },
};

/**
 * The tab is in the URL, not in React state, so a deep link opens the section
 * it names and the page's sub-navigation marks it. The sidebar carries one
 * Settings entry with no `tab`, and `SETTINGS_TABS` in `nav.ts` spells each
 * section's slug; `tabSlug` and `tabFromSlug` read it from there.
 *
 * A URL with no `tab` — someone's bookmark from before this existed, or the
 * sidebar's Settings entry — opens Hours, which is what the page opened on
 * before the tab was addressable.
 */
export const DEFAULT_TAB: Tab = "Hours";

export function tabSlug(tab: Tab): string {
  return (
    SETTINGS_TABS.find((entry) => entry.label === tab)?.tab ?? tab.toLowerCase()
  );
}

export function tabFromSlug(slug: string | null | undefined): Tab {
  const wanted = slug?.toLowerCase();
  return (
    SETTINGS_TABS.find((entry) => entry.tab === wanted)?.label ?? DEFAULT_TAB
  );
}

export function SettingsPage() {
  return (
    <OrgShell
      title="Settings"
      description="The configuration the assistant answers from."
      fixed
    >
      {(org) => <Body org={org} />}
    </OrgShell>
  );
}

function Body({ org }: { org: Org }) {
  const { data, isLoading, error, refetch } = useQuery(getTenantSettings, {
    slug: org.slug,
  });

  const [searchParams, setSearchParams] = useSearchParams();
  const tab = tabFromSlug(searchParams.get("tab"));
  const setTab = (next: Tab) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tabSlug(next));
    // Replace, not push: moving between tabs is not a place a person expects
    // the back button to walk them through, and it did not use to be one.
    setSearchParams(params, { replace: true });
  };

  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);

  useEffect(() => {
    if (data && data.version !== loadedVersion) {
      setDraft(data.config as Draft);
      setLoadedVersion(data.version);
    }
  }, [data, loadedVersion]);

  // A URL with no tab is written out to the one it is showing, so the sidebar
  // can mark the item a person is actually on. Replaced, not pushed: nobody
  // asked to visit two URLs.
  useEffect(() => {
    if (searchParams.get("tab") === null) {
      const params = new URLSearchParams(searchParams);
      params.set("tab", tabSlug(DEFAULT_TAB));
      setSearchParams(params, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  if (isLoading || !data || !draft) {
    return error ? (
      <Problem error={error} />
    ) : (
      <p className="text-muted-foreground text-sm">Loading…</p>
    );
  }

  const readOnly = data.role !== "OWNER";

  async function save() {
    setBusy(true);
    setSaved(null);
    setFieldErrors([]);
    setProblem(null);
    try {
      const result = await saveTenantConfig({ slug: org.slug, config: draft! });
      setSaved(result.version);
      await refetch();
    } catch (caught) {
      const failure = caught as {
        message?: string;
        data?: {
          fieldErrors?: FieldError[];
          data?: { fieldErrors?: FieldError[] };
        };
      };
      // Wasp hands the client the whole response body as `data`, and the body
      // is `{ message, data }`, so an `HttpError`'s own payload is one level in.
      const named =
        failure.data?.data?.fieldErrors ?? failure.data?.fieldErrors ?? [];
      setFieldErrors(named);
      if (named.length === 0) {
        setProblem(failure);
      }
    } finally {
      setBusy(false);
    }
  }

  async function rollBack(version: number) {
    setBusy(true);
    setSaved(null);
    setFieldErrors([]);
    setProblem(null);
    try {
      const result = await rollBackTenantConfig({ slug: org.slug, version });
      setSaved(result.version);
      await refetch();
    } catch (caught) {
      setProblem(caught as { message?: string });
    } finally {
      setBusy(false);
    }
  }

  const tabProps = {
    config: draft,
    schema: data.schema as Record<string, any>,
    onChange: setDraft,
    disabled: readOnly,
    errors: fieldErrors,
  };

  // Branding is the one section that is not the tenant configuration: it has
  // its own save and its own notices, and the configuration's stay off it.
  const configuration = tab !== "Branding";

  return (
    <>
      <p className="text-muted-foreground text-sm">
        {data.tenantId}, version {data.version}.{" "}
        {readOnly
          ? "You are staff here, so this is read only."
          : "A save writes the next version."}
      </p>

      <Separator className="flex-none" />

      <div className="flex flex-1 flex-col space-y-2 overflow-hidden lg:flex-row lg:space-y-0 lg:space-x-12">
        <aside className="top-0 lg:sticky lg:w-1/5">
          <SettingsNav
            items={SETTINGS_TABS.map((entry) => ({
              value: entry.label,
              title: entry.label,
              icon: entry.icon,
              testId: `settings-tab-${entry.tab}`,
            }))}
            value={tab}
            onSelect={(next) => setTab(next as Tab)}
          />
        </aside>

        <div className="flex w-full overflow-y-hidden p-1">
          <ContentSection
            title={tab}
            description={SECTIONS[tab].description}
            actions={
              configuration &&
              !readOnly && (
                <Button
                  type="button"
                  disabled={busy}
                  onClick={save}
                  data-testid="save-settings"
                >
                  Save settings
                </Button>
              )
            }
          >
            {configuration && saved !== null && (
              <Alert data-testid="settings-saved">
                <AlertTitle>Saved as version {saved}</AlertTitle>
                <AlertDescription>
                  The assistant picks it up within thirty seconds.
                </AlertDescription>
              </Alert>
            )}

            {configuration && fieldErrors.length > 0 && (
              <Alert variant="destructive">
                <AlertTitle>
                  The front desk service refused this change
                </AlertTitle>
                <AlertDescription>
                  {fieldErrors.map((fieldError, index) => (
                    <p
                      key={index}
                      data-testid={`field-error-${fieldError.field}`}
                    >
                      {fieldError.path.join(" → ") || "configuration"}:{" "}
                      {fieldError.message}
                    </p>
                  ))}
                </AlertDescription>
              </Alert>
            )}

            {configuration && <Problem error={problem} />}

            {tab === "Hours" && <HoursTab {...tabProps} />}
            {tab === "Services" && <ServicesTab {...tabProps} />}
            {tab === "Team" && <TeamTab {...tabProps} />}
            {tab === "Knowledge" && <KnowledgeTab {...tabProps} />}
            {tab === "Scripts" && <ScriptsTab {...tabProps} />}
            {tab === "Delivery" && <DeliveryTab {...tabProps} />}
            {tab === "Numbers" && (
              <NumbersTab
                config={draft}
                numbers={data.numbers}
                blocks={data.blocks}
                readOnly={readOnly}
                onBlock={async (phone) => {
                  await blockSmsNumber({ slug: org.slug, phone });
                  await refetch();
                }}
                onUnblock={async (phone) => {
                  await unblockSmsNumber({ slug: org.slug, phone });
                  await refetch();
                }}
              />
            )}
            {tab === "Integrations" && (
              <IntegrationsTab slug={org.slug} readOnly={readOnly} />
            )}
            {tab === "Branding" && (
              <BrandingTab
                name={org.name}
                branding={{
                  logoDataUrl: org.logoDataUrl,
                  themePreset: org.themePreset,
                  accentHex: org.accentHex,
                }}
                disabled={readOnly}
                onSave={async (next) => {
                  // The organisation query is invalidated by the action, so
                  // the shell re-reads the look without a reload.
                  await updateOrganizationBranding({ slug: org.slug, ...next });
                }}
              />
            )}
            {tab === "Versions" && (
              <VersionsPanel
                versions={data.versions}
                current={data.version}
                canRollBack={!readOnly}
                busy={busy}
                onRollBack={rollBack}
              />
            )}
          </ContentSection>
        </div>
      </div>
    </>
  );
}
