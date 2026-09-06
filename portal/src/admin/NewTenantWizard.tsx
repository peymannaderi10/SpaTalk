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
import {
  createTenantFromBasics,
  createTenantFromBundle,
} from "wasp/client/operations";
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
import { Checkbox } from "../client/components/ui/checkbox";
import { Input } from "../client/components/ui/input";
import { Label } from "../client/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../client/components/ui/select";
import { Textarea } from "../client/components/ui/textarea";
import { cn } from "../client/utils";
import {
  basicsProblems,
  CANADIAN_TIMEZONES,
  DEFAULT_TIMEZONE,
  defaultBasics,
  OTHER_TIMEZONE,
  runtimeHours,
  WEEKDAYS,
  type BasicsDraft,
  type Weekday,
} from "./basics";
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
 * organisation, give the runtime what it will judge, invite the owner, then
 * read off what still has to be bought and created by hand.
 *
 * Four steps in the kit's form idiom (`src/features/settings/profile` in
 * `satnaing/shadcn-admin`): the registry's label, input and textarea inside
 * one card per step, with the step's buttons in the card's footer.
 *
 * The configuration step is a choice. "Start from the basics" (the default)
 * asks for a timezone, hours, a booking link, the clinic's number and the
 * assistant's name; the runtime renders its starter bundle around them
 * (`POST /internal/tenants/from-basics`). "Upload a bundle" is the five files
 * as before. Either way the portal does not read the configuration: the
 * runtime's loader decides whether it is a tenant, so the wizard and
 * `spatalk tenant import` accept exactly the same thing.
 */

/**
 * What the actions answer, taken from the action itself so the page never has
 * to import server code to know the shape of its own result. Both paths
 * answer the same shape.
 */
type NewTenant = Awaited<ReturnType<typeof createTenantFromBundle>>;

type Step = 1 | 2 | 3 | 4;

type Mode = "basics" | "bundle";

const STEPS: { step: Step; title: string }[] = [
  { step: 1, title: "Organisation" },
  { step: 2, title: "Configuration" },
  { step: 3, title: "Owner" },
  { step: 4, title: "What is left to do" },
];

export function NewTenantWizard({ user }: { user: AuthUser }) {
  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [mode, setMode] = useState<Mode>("basics");
  const [basics, setBasics] = useState<BasicsDraft>(defaultBasics());
  const [bundle, setBundle] = useState<BundleDraft>(emptyBundle());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<NewTenant | null>(null);

  const organisationReady =
    name.trim().length >= 2 && /^[a-z0-9-]+$/.test(slug);
  const problems = basicsProblems(basics);
  const configurationReady =
    mode === "basics" ? problems.length === 0 : isCompleteBundle(bundle);
  const configurationHint =
    mode === "basics"
      ? problems[0]
      : `Still missing: ${missingSlots(bundle)
          .map((slot: BundleSlot) => `${slot}`)
          .join(", ")}.`;

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
      const created =
        mode === "basics"
          ? await createTenantFromBasics({
              name: name.trim(),
              slug,
              ownerEmail: ownerEmail.trim(),
              ownerName: ownerName.trim(),
              basics: {
                timezone: basics.timezone.trim(),
                hours: runtimeHours(basics),
                bookingUrl: basics.bookingUrl.trim(),
                publicPhone: basics.publicPhone.trim(),
                assistantName: basics.assistantName.trim(),
              },
            })
          : await createTenantFromBundle({
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
                  entry.step === step ? "font-medium" : "text-muted-foreground",
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
                What the client signs in to. The slug is the address, and the
                tenant's name in the front desk service when it starts from the
                basics.
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
              <CardTitle>The configuration</CardTitle>
              <CardDescription>
                Start from the basics and let the clinic fill in the rest on its
                Settings pages, or upload the five files of a tenant bundle. The
                front desk service decides whether either makes a tenant; the
                portal does not read them.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <ModeChoice mode={mode} onChange={setMode} />

              {mode === "basics" ? (
                <BasicsForm draft={basics} onChange={setBasics} />
              ) : (
                <div className="space-y-6">
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
                          setBundle({
                            ...bundle,
                            [spec.slot]: event.target.value,
                          })
                        }
                        className="font-mono text-xs"
                      />
                    </Field>
                  ))}
                </div>
              )}
            </CardContent>
            <CardFooter className="gap-4">
              <Back onClick={() => setStep(1)} />
              <Next
                disabled={!configurationReady}
                onClick={() => setStep(3)}
                hint={configurationReady ? undefined : configurationHint}
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
                {mode === "basics" &&
                  " Requests are emailed to this address until the clinic chooses otherwise."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field label="Owner's email address" htmlFor="ownerEmail">
                <Input
                  id="ownerEmail"
                  name="ownerEmail"
                  value={ownerEmail}
                  onChange={(event) => setOwnerEmail(event.target.value)}
                />
              </Field>
              {mode === "basics" && (
                <Field
                  label="Owner's name (optional; who a breach is escalated to)"
                  htmlFor="ownerName"
                >
                  <Input
                    id="ownerName"
                    name="ownerName"
                    value={ownerName}
                    onChange={(event) => setOwnerName(event.target.value)}
                  />
                </Field>
              )}
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

/** The two ways to configure a tenant, as a pair of radio buttons. */
function ModeChoice({
  mode,
  onChange,
}: {
  mode: Mode;
  onChange: (mode: Mode) => void;
}) {
  const options: { mode: Mode; title: string; description: string }[] = [
    {
      mode: "basics",
      title: "Start from the basics",
      description:
        "A timezone, hours, a booking link and a name. The wording, the lexicons and an empty catalogue come from the starter; the clinic adds services, team and knowledge on Settings.",
    },
    {
      mode: "bundle",
      title: "Upload a bundle",
      description:
        "The five files of a tenant bundle, as spatalk tenant import takes them.",
    },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="How to configure the tenant"
      className="grid grid-cols-1 gap-3 sm:grid-cols-2"
    >
      {options.map((option) => (
        <button
          key={option.mode}
          type="button"
          role="radio"
          aria-checked={mode === option.mode}
          data-testid={`wizard-mode-${option.mode}`}
          onClick={() => onChange(option.mode)}
          className={cn(
            "rounded-md border p-4 text-left",
            mode === option.mode
              ? "border-primary bg-muted"
              : "border-border hover:bg-muted/50",
          )}
        >
          <div className="text-sm font-medium">{option.title}</div>
          <p className="text-muted-foreground mt-1 text-xs">
            {option.description}
          </p>
        </button>
      ))}
    </div>
  );
}

/**
 * The basics form. The timezone is a select of Canada's zones with a free-text
 * fallback for anywhere else; the hours are one row per weekday, open or
 * closed, with one span when open — the clinic's Hours page takes several
 * spans and holidays once it is signed in.
 */
function BasicsForm({
  draft,
  onChange,
}: {
  draft: BasicsDraft;
  onChange: (next: BasicsDraft) => void;
}) {
  const known = CANADIAN_TIMEZONES.some(
    (entry) => entry.zone === draft.timezone,
  );
  const [zoneChoice, setZoneChoice] = useState<string>(
    known ? draft.timezone : OTHER_TIMEZONE,
  );

  function chooseZone(choice: string) {
    setZoneChoice(choice);
    onChange({
      ...draft,
      timezone: choice === OTHER_TIMEZONE ? "" : choice,
    });
  }

  function setDay(day: Weekday, patch: Partial<BasicsDraft["hours"][Weekday]>) {
    onChange({
      ...draft,
      hours: { ...draft.hours, [day]: { ...draft.hours[day], ...patch } },
    });
  }

  return (
    <div data-testid="basics-form" className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Timezone" htmlFor="basics-timezone">
          <Select value={zoneChoice} onValueChange={chooseZone}>
            <SelectTrigger
              id="basics-timezone"
              data-testid="basics-timezone"
              className="w-full"
            >
              <SelectValue placeholder={DEFAULT_TIMEZONE} />
            </SelectTrigger>
            <SelectContent>
              {CANADIAN_TIMEZONES.map((entry) => (
                <SelectItem key={entry.zone} value={entry.zone}>
                  {entry.label}
                </SelectItem>
              ))}
              <SelectItem value={OTHER_TIMEZONE}>
                Somewhere else (type the IANA name)
              </SelectItem>
            </SelectContent>
          </Select>
        </Field>
        {zoneChoice === OTHER_TIMEZONE && (
          <Field
            label="IANA timezone name (e.g. Europe/London)"
            htmlFor="basics-timezone-other"
          >
            <Input
              id="basics-timezone-other"
              data-testid="basics-timezone-other"
              value={draft.timezone}
              onChange={(event) =>
                onChange({ ...draft, timezone: event.target.value })
              }
            />
          </Field>
        )}
      </div>

      <div className="space-y-2">
        <span className="text-muted-foreground text-xs uppercase">
          Opening hours
        </span>
        <div className="overflow-hidden rounded-md border">
          {WEEKDAYS.map(([day, label]) => {
            const entry = draft.hours[day];
            return (
              <div
                key={day}
                data-testid={`basics-${day}`}
                className="flex flex-wrap items-center gap-3 border-b px-3 py-2 last:border-b-0"
              >
                <Label
                  htmlFor={`basics-${day}-open`}
                  className="flex w-36 items-center gap-2 text-sm"
                >
                  <Checkbox
                    id={`basics-${day}-open`}
                    data-testid={`basics-${day}-open`}
                    checked={entry.open}
                    onCheckedChange={(checked) =>
                      setDay(day, { open: checked === true })
                    }
                  />
                  {label}
                </Label>
                {entry.open ? (
                  <span className="flex items-center gap-2 text-sm">
                    <Input
                      type="time"
                      className="w-32"
                      aria-label={`${label} opens`}
                      data-testid={`basics-${day}-start`}
                      value={entry.start}
                      onChange={(event) =>
                        setDay(day, { start: event.target.value })
                      }
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="time"
                      className="w-32"
                      aria-label={`${label} closes`}
                      data-testid={`basics-${day}-end`}
                      value={entry.end}
                      onChange={(event) =>
                        setDay(day, { end: event.target.value })
                      }
                    />
                  </span>
                ) : (
                  <span className="text-muted-foreground text-sm">Closed</span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field
          label="Online booking link (texted to callers)"
          htmlFor="basics-booking-url"
        >
          <Input
            id="basics-booking-url"
            data-testid="basics-booking-url"
            placeholder="https://clinic.janeapp.com/"
            value={draft.bookingUrl}
            onChange={(event) =>
              onChange({ ...draft, bookingUrl: event.target.value })
            }
          />
        </Field>
        <Field
          label="The clinic's own number (optional, +1 and ten digits)"
          htmlFor="basics-public-phone"
        >
          <Input
            id="basics-public-phone"
            data-testid="basics-public-phone"
            placeholder="+19055550123"
            value={draft.publicPhone}
            onChange={(event) =>
              onChange({ ...draft, publicPhone: event.target.value })
            }
          />
        </Field>
        <Field
          label="The assistant's name (said in the disclosure)"
          htmlFor="basics-assistant-name"
        >
          <Input
            id="basics-assistant-name"
            data-testid="basics-assistant-name"
            value={draft.assistantName}
            onChange={(event) =>
              onChange({ ...draft, assistantName: event.target.value })
            }
          />
        </Field>
      </div>
    </div>
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
      <Label
        htmlFor={htmlFor}
        className="text-muted-foreground text-xs uppercase"
      >
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
