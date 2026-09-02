import { useEffect, useState } from "react";
import {
  getTenantSettings,
  rollBackTenantConfig,
  saveTenantConfig,
  useQuery,
} from "wasp/client/operations";
import { Button } from "./components/ui/button";
import { OrgShell, Problem, type Org } from "./OrgShell";
import { DeliveryTab } from "./settings/DeliveryTab";
import { HoursTab } from "./settings/HoursTab";
import { IntegrationsTab } from "./settings/Integrations";
import { KnowledgeTab } from "./settings/KnowledgeTab";
import { NumbersTab } from "./settings/NumbersTab";
import { type Draft } from "./settings/schemaFields";
import { ScriptsTab } from "./settings/ScriptsTab";
import { ServicesTab } from "./settings/ServicesTab";
import { VersionsPanel } from "./settings/VersionsPanel";

/**
 * The tenant's configuration, edited through forms built from the runtime's own
 * pydantic schema. A save sends the whole configuration and the runtime stores
 * it as the next version; a refusal comes back with the field that was wrong.
 *
 * Only an owner may save or roll back, and that is enforced by the server
 * operations, not by hiding the button.
 */

type FieldError = { path: string[]; field: string; message: string };

const TABS = [
  "Hours",
  "Services",
  "Knowledge",
  "Scripts",
  "Delivery",
  "Numbers",
  "Integrations",
  "Versions",
] as const;

type Tab = (typeof TABS)[number];

export function SettingsPage() {
  return <OrgShell title="Settings">{(org) => <Body org={org} />}</OrgShell>;
}

function Body({ org }: { org: Org }) {
  const { data, isLoading, error, refetch } = useQuery(getTenantSettings, {
    slug: org.slug,
  });

  const [tab, setTab] = useState<Tab>("Hours");
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
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-muted-foreground text-sm">
          {data.tenantId}, version {data.version}.{" "}
          {readOnly
            ? "You are staff here, so this is read only."
            : "A save writes the next version."}
        </p>
        {!readOnly && (
          <Button
            type="button"
            disabled={busy}
            onClick={save}
            data-testid="save-settings"
          >
            Save settings
          </Button>
        )}
      </div>

      {saved !== null && (
        <p
          data-testid="settings-saved"
          className="border-border mt-4 rounded-md border p-3 text-sm"
        >
          Saved as version {saved}. The assistant picks it up within thirty
          seconds.
        </p>
      )}

      {fieldErrors.length > 0 && (
        <div className="border-border mt-4 space-y-1 rounded-md border p-3 text-sm">
          <p className="text-foreground font-medium">
            The front desk service refused this change:
          </p>
          {fieldErrors.map((fieldError, index) => (
            <p
              key={index}
              data-testid={`field-error-${fieldError.field}`}
              className="text-muted-foreground"
            >
              {fieldError.path.join(" → ") || "configuration"}:{" "}
              {fieldError.message}
            </p>
          ))}
        </div>
      )}

      <Problem error={problem} />

      <div className="border-border mt-6 flex flex-wrap gap-2 border-b pb-3">
        {TABS.map((name) => (
          <Button
            key={name}
            type="button"
            size="sm"
            variant={tab === name ? "default" : "outline"}
            onClick={() => setTab(name)}
          >
            {name}
          </Button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "Hours" && <HoursTab {...tabProps} />}
        {tab === "Services" && <ServicesTab {...tabProps} />}
        {tab === "Knowledge" && <KnowledgeTab {...tabProps} />}
        {tab === "Scripts" && <ScriptsTab {...tabProps} />}
        {tab === "Delivery" && <DeliveryTab {...tabProps} />}
        {tab === "Numbers" && (
          <NumbersTab config={draft} numbers={data.numbers} />
        )}
        {tab === "Integrations" && (
          <IntegrationsTab slug={org.slug} readOnly={readOnly} />
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
      </div>
    </>
  );
}
