import { IconChevronRight } from "@tabler/icons-react";
import { useEffect, useState } from "react";
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
import { Separator } from "../client/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "../client/components/ui/table";
import { formatCad } from "../client/formatting";
import { cn } from "../client/utils";
import { PLAN_MONTHLY_CAD, PLAN_PRICE_TEXT } from "../payment/plans";
import {
  clampClients,
  clampMargin,
  DEFAULT_CLIENTS,
  DEFAULT_MARGIN,
  defaultInputs,
  loadAssumptions,
  marginOf,
  quote,
  saveAssumptions,
  type Quote,
  type QuoteInputs,
  type RatesFile,
  type StorageLike,
  type StoredAssumptions,
} from "./pricing";

/**
 * A price, worked out from what a clinic needs.
 *
 * The face of this page is what an admin turns towards the person they are
 * quoting: the volumes, the monthly price, and what that works out at per call,
 * per minute and per conversation. Everything about our own side of the deal —
 * what the providers charge, the margin on top, how many clinics are sharing
 * the servers, which vendors are behind it — lives inside the **Internal**
 * disclosure, which is shut until the admin opens it. Radix leaves a closed
 * `CollapsibleContent` unmounted, so none of it is in the page at all.
 *
 * The arithmetic is `pricing.ts`, a port of `docs/research/costmodel.py`, and
 * it prices `rates.live_stack` — what production actually runs on — and nothing
 * else. Wasp-free on purpose: `AdminPricingPage` fetches the rates, this draws
 * them, and `QuoteBuilder.test.tsx` renders it from a rates file on disk.
 */
export function QuoteBuilder({ rates }: { rates: RatesFile }) {
  const [inputs, setInputs] = useState<QuoteInputs>(() =>
    defaultInputs(rates, loadAssumptions(browserStorage())),
  );

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

  return (
    <div className="flex flex-col gap-4 sm:gap-6">
      <div className="grid gap-4 lg:grid-cols-2 sm:gap-6">
        <Card>
          <CardHeader>
            <CardTitle>What the clinic needs</CardTitle>
            <CardDescription>
              A month at the front desk. The figures start where a typical
              clinic does.
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
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>The price</CardTitle>
            <CardDescription>
              What this clinic would pay for a month of the front desk.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p
              className="text-4xl font-bold tabular-nums"
              data-testid="pricing-price"
            >
              {formatCad(result.priceCad)}
              <span className="text-muted-foreground ms-2 text-base font-normal">
                a month
              </span>
            </p>

            <Separator />

            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <Unit
                id="pricing-price-per-call"
                label="a call"
                value={result.unitPrices.perCall}
              />
              <Unit
                id="pricing-price-per-minute"
                label="a call minute"
                value={result.unitPrices.perMinute}
              />
              <Unit
                id="pricing-price-per-text"
                label="an SMS conversation"
                value={result.unitPrices.perTextConv}
              />
              <Unit
                id="pricing-price-per-chat"
                label="a chat conversation"
                value={result.unitPrices.perChatConv}
              />
            </div>
            <p className="text-muted-foreground text-xs">
              What the monthly price works out at, at these volumes.
            </p>

            <Separator />

            <p className="text-muted-foreground text-sm">
              The standard plan is{" "}
              <span data-testid="pricing-list-price">{PLAN_PRICE_TEXT}</span> a
              month, whatever the volumes.
            </p>
          </CardContent>
        </Card>
      </div>

      <Internal
        result={result}
        rates={rates}
        margin={inputs.margin}
        clients={inputs.clients}
        onChange={remember}
      />
    </div>
  );
}

/**
 * The agency's own side of the quote, shut by default.
 *
 * What the providers charge, the margin the price carries, how many clinics are
 * splitting the servers and which vendors are behind the figures. None of it is
 * in the document while this is closed, which is what makes the page safe to
 * turn towards the person being quoted.
 */
function Internal({
  result,
  rates,
  margin,
  clients,
  onChange,
}: {
  result: Quote;
  rates: RatesFile;
  margin: number;
  clients: number;
  onChange: (assumptions: StoredAssumptions) => void;
}) {
  const [open, setOpen] = useState(false);
  const isDefault = margin === DEFAULT_MARGIN && clients === DEFAULT_CLIENTS;
  const listMargin = marginOf(result.cogsCad, PLAN_MONTHLY_CAD);

  const atLine = `at ${percent(margin)} margin, ${clients} client${
    clients === 1 ? "" : "s"
  } on the platform`;

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
          Internal
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <Card className="mt-2">
          <CardHeader>
            <CardTitle>What the month costs us</CardTitle>
            <CardDescription data-testid="pricing-at">{atLine}</CardDescription>
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

            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <Unit id="pricing-per-call" label="a call" value={result.perCall} />
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
            <p className="text-muted-foreground text-xs">
              What one of each costs us, before the margin.
            </p>

            <Separator />

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
                  onChange({ margin: DEFAULT_MARGIN, clients: DEFAULT_CLIENTS })
                }
              >
                Reset to 65% and one client
              </Button>
            )}

            <Separator />

            <p className="text-muted-foreground text-sm">
              The standard plan at {PLAN_PRICE_TEXT} a month would carry a
              margin of{" "}
              <span data-testid="pricing-list-margin">
                {listMargin === null ? "—" : percent(listMargin)}
              </span>{" "}
              at these volumes. Stripe holds the price of record.
            </p>

            <p className="text-muted-foreground text-xs" data-testid="pricing-fx">
              Priced on {result.stackLabel}, at the front desk service's own
              rates in US dollars, converted at 1 USD = CA${rates.usd_to_cad}
              {rates._fx_source ? ` (${rates._fx_source})` : ""}.
            </p>
          </CardContent>
        </Card>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** `localStorage`, or nothing at all where the browser refuses it. */
function browserStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
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
