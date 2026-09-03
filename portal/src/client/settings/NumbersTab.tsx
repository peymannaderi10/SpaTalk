import { useState } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { blockStateLabel } from "../formatting";
import { type Draft } from "./schemaFields";

/** A row of the runtime's block list (plan F). */
export type BlockRow = {
  phone: string;
  until: string | null;
  reason: string;
  created_by: string;
  created_at: string;
};

const E164 = /^\+[1-9]\d{7,14}$/;

/** "+1 (905) 555-0123", "905-555-0123" and "+19055550123" all become E.164. */
export function normalizePhone(raw: string): string | null {
  const digits = raw.replace(/[^\d+]/g, "");
  const candidate = digits.startsWith("+")
    ? digits
    : digits.length === 10
      ? `+1${digits}`
      : digits.length === 11 && digits.startsWith("1")
        ? `+${digits}`
        : `+${digits}`;
  return E164.test(candidate) ? candidate : null;
}

/**
 * Read only, and deliberately so: `runtime.tenant_numbers` is authoritative and
 * a number arrives there when the agency buys it, not when someone types it
 * into a form.
 */
export function NumbersTab({
  config,
  numbers,
  blocks = [],
  readOnly = true,
  onBlock,
  onUnblock,
}: {
  config: Draft;
  numbers: { number: string; kind: string }[];
  blocks?: BlockRow[];
  readOnly?: boolean;
  onBlock?: (phone: string) => Promise<void>;
  onUnblock?: (phone: string) => Promise<void>;
}) {
  return (
    <div data-testid="numbers-tab" className="space-y-6 text-sm">
      <p className="text-muted-foreground">
        Numbers are mapped to this tenant by the agency. Ask us to add, move or
        release one.
      </p>

      <table className="w-full text-left">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-2 font-normal">Number</th>
            <th className="py-2 font-normal">Used for</th>
          </tr>
        </thead>
        <tbody>
          {numbers.length === 0 ? (
            <tr>
              <td className="text-muted-foreground py-2" colSpan={2}>
                No number is mapped to this tenant yet.
              </td>
            </tr>
          ) : (
            numbers.map((number) => (
              <tr key={number.number} className="border-border border-t">
                <td className="py-2">{number.number}</td>
                <td className="py-2">
                  {number.kind === "voice" ? "Calls" : "Texts"}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Fact label="Texts are sent from" value={config.sms_from_number} />
        <Fact label="Live transfer goes to" value={config.transfer_number} />
        <Fact label="The clinic's own number" value={config.public_phone} />
        <Fact label="Default booking link" value={config.booking_url_default} />
      </dl>

      <BlockList
        blocks={blocks}
        readOnly={readOnly || !onBlock || !onUnblock}
        onBlock={onBlock}
        onUnblock={onUnblock}
      />
    </div>
  );
}

function reasonLabel(reason: string): string {
  return reason === "flood" ? "Muted by the assistant" : "Blocked by a person";
}

function BlockList({
  blocks,
  readOnly,
  onBlock,
  onUnblock,
}: {
  blocks: BlockRow[];
  readOnly: boolean;
  onBlock?: (phone: string) => Promise<void>;
  onUnblock?: (phone: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function add() {
    const phone = normalizePhone(draft);
    if (!phone) {
      setProblem("Enter the number as +1 followed by ten digits.");
      return;
    }
    setProblem(null);
    setBusy(phone);
    try {
      await onBlock?.(phone);
      setDraft("");
    } catch (caught) {
      setProblem((caught as { message?: string }).message ?? "That number could not be blocked.");
    } finally {
      setBusy(null);
    }
  }

  async function remove(phone: string) {
    setProblem(null);
    setBusy(phone);
    try {
      await onUnblock?.(phone);
    } catch (caught) {
      setProblem((caught as { message?: string }).message ?? "That number could not be unblocked.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section data-testid="sms-blocks" className="space-y-3">
      <h3 className="text-foreground font-medium">Blocked and muted numbers</h3>
      <p className="text-muted-foreground">
        Blocked numbers still reach the carrier, so their texts still cost the
        inbound fee. Their messages are kept in Conversations; nothing is
        answered. A number the assistant muted after a flood frees itself when
        the mute ends.
      </p>

      <table className="w-full text-left">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-2 font-normal">Number</th>
            <th className="py-2 font-normal">State</th>
            <th className="py-2 font-normal">Why</th>
            <th className="py-2 font-normal">By</th>
            {!readOnly && <th className="py-2 font-normal" />}
          </tr>
        </thead>
        <tbody>
          {blocks.length === 0 ? (
            <tr>
              <td className="text-muted-foreground py-2" colSpan={readOnly ? 4 : 5}>
                No number is blocked or muted.
              </td>
            </tr>
          ) : (
            blocks.map((row) => (
              <tr key={row.phone} data-testid="sms-block-row" className="border-border border-t">
                <td className="py-2">{row.phone}</td>
                <td className="py-2">{blockStateLabel(row.until)}</td>
                <td className="py-2">{reasonLabel(row.reason)}</td>
                <td className="text-muted-foreground py-2">{row.created_by}</td>
                {!readOnly && (
                  <td className="py-2 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      data-testid="sms-unblock"
                      disabled={busy === row.phone}
                      onClick={() => remove(row.phone)}
                    >
                      Unblock
                    </Button>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {!readOnly && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void add();
          }}
        >
          <Input
            data-testid="sms-block-input"
            className="max-w-xs"
            placeholder="+1 905 555 0123"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            aria-label="Number to block"
          />
          <Button type="submit" data-testid="sms-block-add" disabled={busy !== null || !draft}>
            Block number
          </Button>
        </form>
      )}
      {problem && (
        <p data-testid="sms-block-problem" className="text-destructive text-sm">
          {problem}
        </p>
      )}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="border-border rounded-lg border p-3">
      <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
      <dd className="text-foreground mt-1">{String(value ?? "—") || "—"}</dd>
    </div>
  );
}
