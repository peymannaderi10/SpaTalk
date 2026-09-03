import { IconBan, IconPhoneOff } from "@tabler/icons-react";
import { type ColumnDef } from "@tanstack/react-table";
import { useState } from "react";

import { DataTable } from "../components/data-table";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
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
 *
 * The blocked and muted numbers are the kit's data table
 * (`src/components/data-table` in `satnaing/shadcn-admin`), small: no toolbar
 * and no pager, because the list is meant to be short.
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
    <div data-testid="numbers-tab" className="space-y-8 text-sm">
      <section className="space-y-3">
        <p className="text-muted-foreground">
          Numbers are mapped to this tenant by the agency. Ask us to add, move
          or release one.
        </p>

        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Number</TableHead>
                <TableHead>Used for</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {numbers.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={2}
                    className="text-muted-foreground h-16 text-center"
                  >
                    No number is mapped to this tenant yet.
                  </TableCell>
                </TableRow>
              ) : (
                numbers.map((number) => (
                  <TableRow key={number.number}>
                    <TableCell className="font-medium">
                      {number.number}
                    </TableCell>
                    <TableCell>
                      {number.kind === "voice" ? "Calls" : "Texts"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Fact label="Texts are sent from" value={config.sms_from_number} />
        <Fact label="Live transfer goes to" value={config.transfer_number} />
        <Fact label="The clinic's own number" value={config.public_phone} />
        <Fact label="Default booking link" value={config.booking_url_default} />
      </section>

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

  const columns: ColumnDef<BlockRow>[] = [
    {
      id: "number",
      accessorFn: (row) => row.phone,
      header: "Number",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.phone}</span>
      ),
    },
    {
      id: "state",
      accessorFn: (row) => blockStateLabel(row.until),
      header: "State",
      cell: ({ row }) => (
        <Badge variant="outline" className="font-normal">
          {blockStateLabel(row.original.until)}
        </Badge>
      ),
    },
    {
      id: "why",
      accessorFn: (row) => reasonLabel(row.reason),
      header: "Why",
    },
    {
      id: "by",
      accessorFn: (row) => row.created_by,
      header: "By",
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.created_by}</span>
      ),
    },
    ...(readOnly
      ? []
      : [
          {
            id: "actions",
            cell: ({ row }: { row: { original: BlockRow } }) => (
              <div className="text-right">
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="sms-unblock"
                  disabled={busy === row.original.phone}
                  onClick={() => remove(row.original.phone)}
                >
                  Unblock
                </Button>
              </div>
            ),
          } as ColumnDef<BlockRow>,
        ]),
  ];

  return (
    <section data-testid="sms-blocks" className="space-y-3">
      <h3 className="text-sm font-medium">Blocked and muted numbers</h3>
      <p className="text-muted-foreground">
        Blocked numbers still reach the carrier, so their texts still cost the
        inbound fee. Their messages are kept in Conversations; nothing is
        answered. A number the assistant muted after a flood frees itself when
        the mute ends.
      </p>

      <DataTable
        columns={columns}
        data={blocks}
        toolbar={false}
        pagination={false}
        testId="sms-block"
        empty="No number is blocked or muted."
      />

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
            <IconBan className="size-4" />
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
    <Card className="gap-0 py-4">
      <CardContent className="px-4">
        <p className="text-muted-foreground text-xs uppercase">{label}</p>
        <p className="text-foreground mt-1 flex items-center gap-2 break-all">
          {String(value ?? "—") || (
            <>
              <IconPhoneOff className="text-muted-foreground size-4" />—
            </>
          )}
        </p>
      </CardContent>
    </Card>
  );
}
