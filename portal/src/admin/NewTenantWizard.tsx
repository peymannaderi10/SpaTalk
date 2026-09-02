import { useState, type ChangeEvent } from "react";
import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { createTenantFromBundle } from "wasp/client/operations";
import {
  BUNDLE_SLOTS,
  emptyBundle,
  isCompleteBundle,
  missingSlots,
  slotForFilename,
  type BundleDraft,
  type BundleSlot,
} from "./bundle";
import { DefaultLayout } from "./layout/DefaultLayout";

/**
 * Onboarding a client, in the order that leaves the least to undo: name the
 * organisation, give the runtime the bundle it will judge, invite the owner,
 * then read off what still has to be bought and created by hand.
 *
 * The portal does not read the bundle. The five files go to the runtime whose
 * loader decides whether they are a tenant, so the wizard and
 * `spatalk tenant import` accept exactly the same thing.
 */

/**
 * What the action answers, taken from the action itself so the page never has
 * to import server code to know the shape of its own result.
 */
type NewTenant = Awaited<ReturnType<typeof createTenantFromBundle>>;

type Step = 1 | 2 | 3 | 4;

const STEPS: { step: Step; title: string }[] = [
  { step: 1, title: "Organisation" },
  { step: 2, title: "Bundle" },
  { step: 3, title: "Owner" },
  { step: 4, title: "What is left to do" },
];

export function NewTenantWizard({ user }: { user: AuthUser }) {
  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [bundle, setBundle] = useState<BundleDraft>(emptyBundle());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<NewTenant | null>(null);

  const organisationReady =
    name.trim().length >= 2 && /^[a-z0-9-]+$/.test(slug);
  const bundleReady = isCompleteBundle(bundle);

  function takeFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    setProblem(null);
    Promise.all(
      files.map(async (file) => ({
        slot: slotForFilename(file.name),
        name: file.name,
        text: await file.text(),
      })),
    ).then((read) => {
      const unknown = read.filter((entry) => entry.slot === null);
      if (unknown.length > 0) {
        setProblem(
          `Not part of a bundle: ${unknown
            .map((entry) => entry.name)
            .join(", ")}. ` +
            `A bundle is ${BUNDLE_SLOTS.map((spec) => spec.filename).join(
              ", ",
            )}.`,
        );
      }
      setBundle((current) => {
        const next = { ...current };
        for (const entry of read) {
          if (entry.slot) {
            next[entry.slot] = entry.text;
          }
        }
        return next;
      });
    });
  }

  async function create() {
    setBusy(true);
    setProblem(null);
    try {
      const created = await createTenantFromBundle({
        name: name.trim(),
        slug,
        ownerEmail: ownerEmail.trim(),
        bundle,
      });
      setResult(created);
      setStep(4);
    } catch (caught) {
      setProblem(
        (caught as { message?: string }).message ??
          "The tenant could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <DefaultLayout user={user}>
      <h1 className="text-foreground text-2xl font-semibold">New tenant</h1>

      <ol className="text-muted-foreground mt-4 flex flex-wrap gap-4 text-sm">
        {STEPS.map((entry) => (
          <li
            key={entry.step}
            className={
              entry.step === step ? "text-foreground font-medium" : undefined
            }
          >
            {entry.step}. {entry.title}
          </li>
        ))}
      </ol>

      {problem && (
        <p
          data-testid="wizard-problem"
          className="border-border text-foreground mt-6 rounded-md border p-4 text-sm"
        >
          {problem}
        </p>
      )}

      {step === 1 && (
        <section className="mt-8 max-w-xl space-y-4">
          <Field label="Organisation name">
            <input
              name="organizationName"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="border-border w-full rounded-md border px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Address (the client signs in at /app/<slug>)">
            <input
              name="organizationSlug"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              className="border-border w-full rounded-md border px-3 py-2 text-sm"
            />
          </Field>
          <Next
            disabled={!organisationReady}
            onClick={() => setStep(2)}
            hint={
              organisationReady
                ? undefined
                : "A name, and a slug of lowercase letters, digits and hyphens."
            }
          />
        </section>
      )}

      {step === 2 && (
        <section className="mt-8 space-y-6">
          <div>
            <p className="text-muted-foreground text-sm">
              The five files of the tenant bundle. Choose them all at once, or
              paste them. The front desk service decides whether they are valid;
              the portal does not read them.
            </p>
            <input
              type="file"
              multiple
              data-testid="bundle-files"
              onChange={takeFiles}
              className="mt-3 text-sm"
            />
          </div>

          {BUNDLE_SLOTS.map((spec) => (
            <Field
              key={spec.slot}
              label={`${spec.filename} — ${spec.description}`}
            >
              <textarea
                name={`bundle-${spec.slot}`}
                rows={6}
                value={bundle[spec.slot]}
                onChange={(event) =>
                  setBundle({ ...bundle, [spec.slot]: event.target.value })
                }
                className="border-border w-full rounded-md border px-3 py-2 font-mono text-xs"
              />
            </Field>
          ))}

          <div className="flex items-center gap-4">
            <Back onClick={() => setStep(1)} />
            <Next
              disabled={!bundleReady}
              onClick={() => setStep(3)}
              hint={
                bundleReady
                  ? undefined
                  : `Still missing: ${missingSlots(bundle)
                      .map((slot: BundleSlot) => `${slot}`)
                      .join(", ")}.`
              }
            />
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="mt-8 max-w-xl space-y-4">
          <Field label="Owner's email address">
            <input
              name="ownerEmail"
              value={ownerEmail}
              onChange={(event) => setOwnerEmail(event.target.value)}
              className="border-border w-full rounded-md border px-3 py-2 text-sm"
            />
          </Field>
          <p className="text-muted-foreground text-sm">
            They are emailed a single-use invitation that expires in seven days.
          </p>
          <div className="flex items-center gap-4">
            <Back onClick={() => setStep(2)} />
            <button
              type="button"
              data-testid="wizard-create"
              disabled={busy || ownerEmail.trim().length === 0}
              onClick={create}
              className="border-border rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            >
              {busy ? "Creating…" : "Create tenant"}
            </button>
          </div>
        </section>
      )}

      {step === 4 && result && <Done result={result} />}
    </DefaultLayout>
  );
}

function Done({ result }: { result: NewTenant }) {
  const tenant = result.runtimeTenantId;
  const slackChannel = `#${tenant}-frontdesk`;
  const webhookVariable = `${tenant
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "_")}_SLACK_WEBHOOK`;

  return (
    <section className="mt-8 space-y-8">
      <div
        data-testid="wizard-result"
        className="border-border rounded-md border p-4 text-sm"
      >
        <p className="text-foreground font-medium">
          {tenant} is configuration version {result.configVersion} in the front
          desk service.
        </p>
        <p className="text-muted-foreground mt-1">
          {result.organizationCreated
            ? "The organisation was created"
            : "An organisation for this tenant already existed and was kept"}
          , at{" "}
          <Link className="underline" to={`/app/${result.organizationSlug}`}>
            /app/{result.organizationSlug}
          </Link>
          .
        </p>
      </div>

      <div
        data-testid="wizard-invitation"
        className="border-border rounded-md border p-4 text-sm"
      >
        <p className="text-foreground font-medium">
          {result.invitation.email} has been invited as the owner.
        </p>
        <p className="text-muted-foreground mt-1 break-all">
          If the email does not arrive, hand them this link:{" "}
          {result.invitation.inviteUrl}
        </p>
      </div>

      <div data-testid="wizard-checklist">
        <h2 className="text-foreground text-lg font-medium">
          What still has to be done by hand
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          None of this can be done from the portal. The steps are in{" "}
          <code>docs/runbooks/accounts-and-env.md</code>.
        </p>
        <ul className="mt-3 space-y-3 text-sm">
          <Todo where="§ 3, steps 4 and 5">
            Buy the local voice number in Telnyx and assign it to the{" "}
            <code>spatalk-runtime</code> TeXML application.
          </Todo>
          <Todo where="§ 3, steps 6 to 8">
            Buy the toll-free number, assign it to the <code>spatalk-sms</code>{" "}
            messaging profile, and submit toll-free verification. Until it
            passes, texts from that number are dropped.
          </Todo>
          <Todo where="§ 3, step 9">
            Map both numbers to this tenant:
            <pre className="bg-muted mt-1 overflow-x-auto rounded p-2 text-xs">
              {`spatalk numbers add <local E.164> ${tenant} voice\nspatalk numbers add <toll-free E.164> ${tenant} sms`}
            </pre>
            Then set <code>sms_from_number</code> in the tenant's settings.
          </Todo>
          <Todo where="§ 8, step 4">
            Create the Slack channel <code>{slackChannel}</code>, add an
            incoming webhook for it, and put the URL in{" "}
            <code>{webhookVariable}</code> on the runtime. The bundle refers to
            that variable by name; the secret never goes in the bundle.
          </Todo>
          <Todo where="§ 10">
            Subscribe the organisation to the Front Desk plan so billing starts.
          </Todo>
        </ul>
      </div>

      <p className="text-sm">
        <Link className="underline" to="/admin/tenants">
          Back to the tenants table
        </Link>
      </p>
    </section>
  );
}

function Todo({
  where,
  children,
}: {
  where: string;
  children: React.ReactNode;
}) {
  return (
    <li className="border-border rounded-md border p-3">
      <div className="text-muted-foreground text-xs uppercase">
        accounts-and-env.md {where}
      </div>
      <div className="text-foreground mt-1">{children}</div>
    </li>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-muted-foreground text-xs uppercase">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Next({
  disabled,
  onClick,
  hint,
}: {
  disabled: boolean;
  onClick: () => void;
  hint?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        data-testid="wizard-next"
        disabled={disabled}
        onClick={onClick}
        className="border-border rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
      >
        Next
      </button>
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      data-testid="wizard-back"
      onClick={onClick}
      className="text-muted-foreground hover:text-foreground text-sm underline"
    >
      Back
    </button>
  );
}
