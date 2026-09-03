import {
  IconArrowLeft,
  IconArrowRight,
  IconCheck,
  IconClipboardCheck,
  IconMailForward,
} from "@tabler/icons-react";
import { useState, type ChangeEvent } from "react";
import { Link } from "react-router";
import { type AuthUser } from "wasp/auth";
import { createTenantFromBundle } from "wasp/client/operations";
import { PageHeader } from "../client/components/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../client/components/ui/alert";
import { Button } from "../client/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import { Input } from "../client/components/ui/input";
import { Label } from "../client/components/ui/label";
import { Textarea } from "../client/components/ui/textarea";
import { cn } from "../client/utils";
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
 * Four steps in the kit's form idiom (`src/features/settings/profile` in
 * `satnaing/shadcn-admin`): the registry's label, input and textarea inside
 * one card per step, with the step's buttons in the card's footer.
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
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="New tenant"
          description="Four steps, in the order that leaves the least to undo."
        />

        <ol className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          {STEPS.map((entry) => (
            <li key={entry.step} className="flex items-center gap-2">
              <span
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  entry.step === step
                    ? "bg-primary text-primary-foreground border-transparent"
                    : entry.step < step
                      ? "bg-muted text-muted-foreground"
                      : "text-muted-foreground",
                )}
              >
                {entry.step < step ? (
                  <IconCheck className="size-3" />
                ) : (
                  entry.step
                )}
              </span>
              <span
                className={cn(
                  entry.step === step
                    ? "font-medium"
                    : "text-muted-foreground",
                )}
              >
                {entry.title}
              </span>
            </li>
          ))}
        </ol>

        {problem && (
          <Alert variant="destructive" data-testid="wizard-problem">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        {step === 1 && (
          <Card className="max-w-xl">
            <CardHeader>
              <CardTitle>The organisation</CardTitle>
              <CardDescription>
                What the client signs in to. The slug is the address.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field label="Organisation name" htmlFor="organizationName">
                <Input
                  id="organizationName"
                  name="organizationName"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field
                label="Address (the client signs in at /app/<slug>)"
                htmlFor="organizationSlug"
              >
                <Input
                  id="organizationSlug"
                  name="organizationSlug"
                  value={slug}
                  onChange={(event) => setSlug(event.target.value)}
                />
              </Field>
            </CardContent>
            <CardFooter>
              <Next
                disabled={!organisationReady}
                onClick={() => setStep(2)}
                hint={
                  organisationReady
                    ? undefined
                    : "A name, and a slug of lowercase letters, digits and hyphens."
                }
              />
            </CardFooter>
          </Card>
        )}

        {step === 2 && (
          <Card>
            <CardHeader>
              <CardTitle>The bundle</CardTitle>
              <CardDescription>
                The five files of the tenant bundle. Choose them all at once, or
                paste them. The front desk service decides whether they are
                valid; the portal does not read them.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <Input
                type="file"
                multiple
                data-testid="bundle-files"
                onChange={takeFiles}
                className="max-w-md"
              />

              {BUNDLE_SLOTS.map((spec) => (
                <Field
                  key={spec.slot}
                  label={`${spec.filename} — ${spec.description}`}
                  htmlFor={`bundle-${spec.slot}`}
                >
                  <Textarea
                    id={`bundle-${spec.slot}`}
                    name={`bundle-${spec.slot}`}
                    rows={6}
                    value={bundle[spec.slot]}
                    onChange={(event) =>
                      setBundle({ ...bundle, [spec.slot]: event.target.value })
                    }
                    className="font-mono text-xs"
                  />
                </Field>
              ))}
            </CardContent>
            <CardFooter className="gap-4">
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
            </CardFooter>
          </Card>
        )}

        {step === 3 && (
          <Card className="max-w-xl">
            <CardHeader>
              <CardTitle>The owner</CardTitle>
              <CardDescription>
                They are emailed a single-use invitation that expires in seven
                days.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Field label="Owner's email address" htmlFor="ownerEmail">
                <Input
                  id="ownerEmail"
                  name="ownerEmail"
                  value={ownerEmail}
                  onChange={(event) => setOwnerEmail(event.target.value)}
                />
              </Field>
            </CardContent>
            <CardFooter className="gap-4">
              <Back onClick={() => setStep(2)} />
              <Button
                type="button"
                data-testid="wizard-create"
                disabled={busy || ownerEmail.trim().length === 0}
                onClick={create}
              >
                {busy ? "Creating…" : "Create tenant"}
              </Button>
            </CardFooter>
          </Card>
        )}

        {step === 4 && result && <Done result={result} />}
      </div>
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
    <div className="space-y-4">
      <Alert data-testid="wizard-result">
        <IconCheck />
        <AlertTitle>
          {tenant} is configuration version {result.configVersion} in the front
          desk service
        </AlertTitle>
        <AlertDescription>
          <p>
            {result.organizationCreated
              ? "The organisation was created"
              : "An organisation for this tenant already existed and was kept"}
            , at{" "}
            <Link
              className="underline underline-offset-4"
              to={`/app/${result.organizationSlug}`}
            >
              /app/{result.organizationSlug}
            </Link>
            .
          </p>
        </AlertDescription>
      </Alert>

      <Alert data-testid="wizard-invitation">
        <IconMailForward />
        <AlertTitle>
          {result.invitation.email} has been invited as the owner
        </AlertTitle>
        <AlertDescription>
          <p className="break-all">
            If the email does not arrive, hand them this link:{" "}
            {result.invitation.inviteUrl}
          </p>
        </AlertDescription>
      </Alert>

      <Card data-testid="wizard-checklist">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <IconClipboardCheck className="size-5" />
            What still has to be done by hand
          </CardTitle>
          <CardDescription>
            None of this can be done from the portal. The steps are in{" "}
            <code>docs/runbooks/accounts-and-env.md</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3 text-sm">
            <Todo where="§ 3, steps 4 and 5">
              Buy the local voice number in Telnyx and assign it to the{" "}
              <code>spatalk-runtime</code> TeXML application.
            </Todo>
            <Todo where="§ 3, steps 6 to 8">
              Buy the toll-free number, assign it to the{" "}
              <code>spatalk-sms</code> messaging profile, and submit toll-free
              verification. Until it passes, texts from that number are dropped.
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
              <code>{webhookVariable}</code> on the runtime. The bundle refers
              to that variable by name; the secret never goes in the bundle.
            </Todo>
            <Todo where="§ 10">
              Subscribe the organisation to the Front Desk plan so billing
              starts.
            </Todo>
          </ul>
        </CardContent>
        <CardFooter>
          <Button variant="outline" asChild>
            <Link to="/admin/tenants">
              <IconArrowLeft className="size-4" />
              Back to the tenants table
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
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
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-muted-foreground text-xs uppercase">
        {label}
      </Label>
      {children}
    </div>
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
    <div className="flex flex-wrap items-center gap-3">
      <Button
        type="button"
        data-testid="wizard-next"
        disabled={disabled}
        onClick={onClick}
      >
        Next
        <IconArrowRight className="size-4" />
      </Button>
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      data-testid="wizard-back"
      onClick={onClick}
    >
      <IconArrowLeft className="size-4" />
      Back
    </Button>
  );
}
