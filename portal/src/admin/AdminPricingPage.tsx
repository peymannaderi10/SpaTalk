import { IconChevronRight, IconCoin } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { type AuthUser } from "wasp/auth";
import { getAgencyTenants, getRates, useQuery } from "wasp/client/operations";
import { BRAND } from "../client/brand";
import { EmptyState } from "../client/components/empty-state";
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
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../client/components/ui/collapsible";
import { Input } from "../client/components/ui/input";
import { Label } from "../client/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../client/components/ui/select";
import { Separator } from "../client/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../client/components/ui/table";
import { formatCad, formatMinutes } from "../client/formatting";
import { cn } from "../client/utils";
import { PLAN_MONTHLY_CAD, PLAN_PRICE_TEXT } from "../payment/plans";
import { type AgencyTenantRow } from "./agency";
import { DefaultLayout } from "./layout/DefaultLayout";
import {
  clampClients,
  clampMargin,
  DEFAULT_CLIENTS,
  DEFAULT_MARGIN,
  defaultInputs,
  loadAssumptions,
  marginOf,
  measured,
  quote,
  saveAssumptions,
  type QuoteInputs,
  type RatesFile,
  type StorageLike,
  type StoredAssumptions,
} from "./pricing";

/**
 * What to quote a client, worked out from what they need.
 *
 * The page is the kit's settings idiom (`src/features/settings` in
 * `satnaing/shadcn-admin`): a header, a form card, and the answer in a card
 * beside it. The arithmetic is `pricing.ts`, a port of
 * `docs/research/costmodel.py` pinned to the Python's own figures; the rates it
 * works from are the runtime's file, fetched through `getRates`, never a copy
 * kept in the portal.
 *
 * The measured column is there because the model is a model. It assumes far
 * fewer tokens a call than the live runtime has been using, so beside every
 * modelled unit cost the page puts what one real tenant actually cost this
 * month, straight from `est_cost_cad`.
 */
export function AdminPricingPage({ user }: { user: AuthUser }) {
  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Pricing"
          description={`What a month of ${BRAND.name} costs the agency for one client, and what to charge for it.`}
        />
        <Body />
      </div>
    </DefaultLayout>
  );
}

function Body() {
  const rates = useQuery(getRates);
  const tenants = useQuery(getAgencyTenants);

  if (rates.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  }
  if (rates.error || !rates.data) {
    return (
      <Alert variant="destructive" data-testid="pricing-problem">
        <AlertTitle>The provider rates could not be read</AlertTitle>
        <AlertDescription>
          {rates.error?.message ??
            "The front desk service did not answer with its rate file, so there is nothing to quote against."}
        </AlertDescription>
      </Alert>
    );
  }

  return <Builder rates={rates.data} tenants={tenants.data ?? []} />;
}

/** `localStorage`, or nothing at all where the browser refuses it. */
function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function Builder({
  rates,
  tenants,
}: {
  rates: RatesFile;
  tenants: AgencyTenantRow[];
}) {
  const [inputs, setInputs] = useState<QuoteInputs>(() =>
    defaultInputs(rates, loadAssumptions(browserStorage())),
  );
  const [tenantSlug, setTenantSlug] = useState<string>(
    () => tenants[0]?.slug ?? "",
  );

  // The tenants arrive after the rates do, so the first one becomes the
  // measured column as soon as there is one to choose.
  useEffect(() => {
    if (tenantSlug === "" && tenants.length > 0) {
      setTenantSlug(tenants[0].slug);
    }
  }, [tenants, tenantSlug]);

  const set = <K extends keyof QuoteInputs>(key: K, value: QuoteInputs[K]) =>
    setInputs((previous) => ({ ...previous, [key]: value }));

  /** Margin and client count are the two this browser remembers. */
  const remember = (assumptions: StoredAssumptions) => {
    setInputs((previous) => ({
      ...previous,
      margin: assumptions.margin,
      clients: assumptions.clients,
    }));
    saveAssumptions(assumptions, browserStorage());
  };

  const result = quote(inputs, rates);
  const listMargin = marginOf(result.cogsCad, PLAN_MONTHLY_CAD);
  const chosen = tenants.find((tenant) => tenant.slug === tenantSlug) ?? null;
  // A tenant the runtime could not answer for has zeroes in its row and a
  // sentence saying why; zeroes are not a measurement, so the column stays
  // empty and the sentence is shown instead.
  const actual = chosen && !chosen.problem ? measured(chosen) : null;

  const atLine = `at ${percent(inputs.margin)} margin, ${inputs.clients} client${
    inputs.clients === 1 ? "" : "s"
  } on the platform`;

  return (
    <div className="flex flex-col gap-4 sm:gap-6">
      <div className="grid gap-4 lg:grid-cols-2 sm:gap-6">
        <Card>
          <CardHeader>
            <CardTitle>What the client needs</CardTitle>
            <CardDescription>
              A month at one clinic. The figures start at the volumes the rate
              file assumes.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <NumberField
              id="pricing-calls"
              label="Calls a month"
              value={inputs.callsPerMonth}
              min={0}
              onChange={(value) => set("callsPerMonth", value)}
            />
            <NumberField
              id="pricing-avg-minutes"
              label="Average call, minutes"
              value={inputs.avgCallMinutes}
              min={0}
              step={0.5}
              onChange={(value) => set("avgCallMinutes", value)}
            />
            <NumberField
              id="pricing-sms-convs"
              label="SMS conversations a month"
              value={inputs.smsConvsPerMonth}
              min={0}
              onChange={(value) => set("smsConvsPerMonth", value)}
            />
            <NumberField
              id="pricing-chat-convs"
              label="Chat conversations a month"
              value={inputs.chatConvsPerMonth}
              min={0}
              onChange={(value) => set("chatConvsPerMonth", value)}
            />
            <NumberField
              id="pricing-outbound"
              label="Outbound messages a month"
              value={inputs.outboundMsgsPerMonth}
              min={0}
              onChange={(value) => set("outboundMsgsPerMonth", value)}
            />
            <div className="hidden sm:block" />
            <StackField
              id="pricing-voice-stack"
              label="Voice stack"
              value={inputs.voiceStack}
              options={Object.keys(rates.voice_stacks)}
              onChange={(value) => set("voiceStack", value)}
            />
            <StackField
              id="pricing-text-stack"
              label="Text stack"
              value={inputs.textStack}
              options={Object.keys(rates.text_stacks)}
              onChange={(value) => set("textStack", value)}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>The quote</CardTitle>
            <CardDescription>
              What the month costs the agency, and what to charge for it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Table>
              <TableBody>
                {result.breakdown.map((line) => (
                  <TableRow key={line.id}>
                    <TableCell className="ps-0">{line.label}</TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid={`pricing-line-${line.id}`}
                    >
                      {formatCad(line.cad)}
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow>
                  <TableCell className="ps-0 font-medium">
                    Cost of goods, a month
                  </TableCell>
                  <TableCell
                    className="pe-0 text-right font-medium tabular-nums"
                    data-testid="pricing-cogs"
                  >
                    {formatCad(result.cogsCad)}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>

            <Separator />

            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <p className="text-muted-foreground text-sm">
                  Quote this a month
                </p>
                <p
                  className="text-muted-foreground text-xs"
                  data-testid="pricing-at"
                >
                  {atLine}
                </p>
              </div>
              <p
                className="text-3xl font-bold tabular-nums"
                data-testid="pricing-price"
              >
                {formatCad(result.priceCad)}
              </p>
            </div>

            <Separator />

            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <Unit
                id="pricing-per-call"
                label="a call"
                value={result.perCall}
              />
              <Unit
                id="pricing-per-minute"
                label="a call minute"
                value={result.perMinute}
              />
              <Unit
                id="pricing-per-text"
                label="an SMS conversation"
                value={result.perTextConv}
              />
              <Unit
                id="pricing-per-chat"
                label="a chat conversation"
                value={result.perChatConv}
              />
            </div>

            <Separator />

            <div className="text-muted-foreground space-y-1 text-sm">
              <p>
                The plan's list price is{" "}
                <span data-testid="pricing-list-price">{PLAN_PRICE_TEXT}</span> a
                month, which at these volumes would carry a margin of{" "}
                <span data-testid="pricing-list-margin">
                  {listMargin === null ? "—" : percent(listMargin)}
                </span>
                . Stripe holds the price of record.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Measured, this month</CardTitle>
          <CardDescription>
            What one tenant actually cost, from the same usage figures the
            overview shows — beside what the model above says it should have.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {tenants.length === 0 ? (
            <EmptyState
              title="No tenant to measure yet"
              description="A client's real cost appears here once the runtime has counted a month for one."
              icon={IconCoin}
              className="border-0"
              testId="pricing-no-tenants"
            />
          ) : (
            <>
              <div className="flex flex-col gap-1.5 sm:max-w-sm">
                <Label htmlFor="pricing-tenant">Tenant</Label>
                <Select value={tenantSlug} onValueChange={setTenantSlug}>
                  <SelectTrigger id="pricing-tenant" data-testid="pricing-tenant">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {tenants.map((tenant) => (
                      <SelectItem key={tenant.slug} value={tenant.slug}>
                        {tenant.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead />
                    <TableHead className="text-right">Modelled</TableHead>
                    <TableHead className="text-right">Measured</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell className="ps-0">Calls</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {inputs.callsPerMonth}
                    </TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid="pricing-measured-calls"
                    >
                      {actual ? actual.calls : "—"}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="ps-0">Call minutes</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMinutes(
                        inputs.callsPerMonth * inputs.avgCallMinutes,
                      )}
                    </TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid="pricing-measured-minutes"
                    >
                      {actual ? formatMinutes(actual.minutes) : "—"}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="ps-0">Provider cost</TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      data-testid="pricing-model-variable"
                    >
                      {formatCad(variableCad(result))}
                    </TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid="pricing-measured-cost"
                    >
                      {actual ? formatCad(actual.costCad) : "—"}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="ps-0">Cost a call</TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      data-testid="pricing-model-per-call"
                    >
                      {unitCad(result.perCall)}
                    </TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid="pricing-measured-per-call"
                    >
                      {actual?.perCall === null || actual === null
                        ? "—"
                        : unitCad(actual.perCall)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="ps-0">Cost a call minute</TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      data-testid="pricing-model-per-minute"
                    >
                      {unitCad(result.perMinute)}
                    </TableCell>
                    <TableCell
                      className="pe-0 text-right tabular-nums"
                      data-testid="pricing-measured-per-minute"
                    >
                      {actual?.perMinute === null || actual === null
                        ? "—"
                        : unitCad(actual.perMinute)}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>

              {chosen?.problem && (
                <Alert variant="destructive" data-testid="pricing-measured-problem">
                  <AlertTitle>
                    Nothing measured for {chosen.name}
                  </AlertTitle>
                  <AlertDescription>{chosen.problem}</AlertDescription>
                </Alert>
              )}

              <p className="text-muted-foreground text-sm">
                The two disagree mostly on tokens. The model assumes{" "}
                {Math.round(
                  (rates.assumptions.input_tokens_uncached_per_turn +
                    rates.assumptions.input_tokens_cached_per_turn) *
                    rates.assumptions.turns_per_minute *
                    inputs.avgCallMinutes,
                ).toLocaleString()}{" "}
                input tokens in a call of this length; the runtime measured
                about 190,000 a call on 3 September 2026. The measured column
                divides the month's whole provider cost — calls, texts and
                chats together — by its calls and its minutes, so it is the
                outside edge of what a call cost, not the voice part alone.
                Where the two disagree, the measured figure is the one the
                providers billed.
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <p className="text-muted-foreground text-xs" data-testid="pricing-fx">
        Provider rates are the front desk service's own file, in US dollars,
        converted at 1 USD = CA${rates.usd_to_cad}
        {rates._fx_source ? ` (${rates._fx_source})` : ""}.
      </p>

      <Assumptions
        margin={inputs.margin}
        clients={inputs.clients}
        onChange={remember}
      />
    </div>
  );
}

/**
 * The two numbers that are the agency's own policy rather than the client's
 * needs, kept out of the main form and out of the way.
 *
 * They are remembered in this browser's `localStorage` — per browser and per
 * admin, not shared — and the quote prints both beside its answer, so a
 * remembered value is never a hidden one.
 */
function Assumptions({
  margin,
  clients,
  onChange,
}: {
  margin: number;
  clients: number;
  onChange: (assumptions: StoredAssumptions) => void;
}) {
  const [open, setOpen] = useState(false);
  const isDefault = margin === DEFAULT_MARGIN && clients === DEFAULT_CLIENTS;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="-ms-2"
          data-testid="pricing-assumptions"
        >
          <IconChevronRight
            className={cn("size-4 transition-transform", open && "rotate-90")}
          />
          Assumptions
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <Card className="mt-2">
          <CardContent className="space-y-4 pt-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField
                id="pricing-margin"
                label="Margin, %"
                value={Math.round(margin * 1000) / 10}
                min={0}
                max={99}
                step={1}
                onChange={(value) =>
                  onChange({ margin: clampMargin(value / 100), clients })
                }
              />
              <NumberField
                id="pricing-clients"
                label="Clients on the platform"
                value={clients}
                min={1}
                step={1}
                onChange={(value) =>
                  onChange({ margin, clients: clampClients(value) })
                }
              />
            </div>
            <p className="text-muted-foreground text-sm">
              Margin, not markup: 65% margin means the cost is 35% of the price,
              so a cost of CA$100 is quoted at CA$285.71. The client count is
              how many clinics share the platform's fixed cost — more of them
              means a smaller share each. Both are remembered in this browser
              only.
            </p>
            {!isDefault && (
              <Button
                variant="link"
                size="sm"
                className="-ms-1 h-auto p-0"
                data-testid="pricing-reset"
                onClick={() =>
                  onChange({
                    margin: DEFAULT_MARGIN,
                    clients: DEFAULT_CLIENTS,
                  })
                }
              >
                Reset to 65% and one client
              </Button>
            )}
          </CardContent>
        </Card>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Unit({
  id,
  label,
  value,
}: {
  id: string;
  label: string;
  value: number;
}) {
  return (
    <div>
      <p className="font-medium tabular-nums" data-testid={id}>
        {unitCad(value)}
      </p>
      <p className="text-muted-foreground text-xs">{label}</p>
    </div>
  );
}

/**
 * A number the person types. It keeps its own text so a half-typed figure is
 * not rewritten under them, and reports a number only when there is one.
 */
function NumberField({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));

  useEffect(() => {
    if (Number(text) !== value) {
      setText(String(value));
    }
    // Only when the value changes from outside — a reset, a remembered figure.
  }, [value]);

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        data-testid={id}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={text}
        onChange={(event) => {
          const raw = event.target.value;
          setText(raw);
          const parsed = Number(raw);
          if (raw !== "" && Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
      />
    </div>
  );
}

function StackField({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 sm:col-span-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} data-testid={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/**
 * The four variable lines of a quote: what the providers charge for the work
 * itself, which is the part `est_cost_cad` is a measurement of. The two fixed
 * lines — this client's numbers and its share of the servers — are the
 * agency's bill, not the runtime's, so they are left out of the comparison.
 */
function variableCad(result: ReturnType<typeof quote>): number {
  const fixed = new Set(["per-tenant-fixed", "platform-share"]);
  return result.breakdown
    .filter((line) => !fixed.has(line.id))
    .reduce((total, line) => total + line.cad, 0);
}

/** A per-call or per-minute figure, where two decimal places would say $0.03. */
function unitCad(value: number): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(value);
}

function percent(fraction: number): string {
  return `${Math.round(fraction * 1000) / 10}%`;
}
