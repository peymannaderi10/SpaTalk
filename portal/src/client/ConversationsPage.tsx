import { IconHeartRateMonitor, IconMessages } from "@tabler/icons-react";
import {
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
} from "@tanstack/react-table";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  blockSmsNumber,
  getTenantConversations,
  getTenantSettings,
  readConversation,
  useQuery,
} from "wasp/client/operations";
import {
  DataTableColumnHeader,
  DataTablePagination,
  DataTableToolbar,
} from "./components/data-table";
import { EmptyState } from "./components/empty-state";
import { Badge } from "./components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./components/ui/table";
import {
  bandLabel,
  channelLabel,
  controllerLabel,
  formatDateTime,
  formatDuration,
  notesLabel,
} from "./formatting";
import { OrgShell, Problem, type Org } from "./OrgShell";
import { TranscriptSheet, type TranscriptDetail } from "./TranscriptSheet";

type Detail = TranscriptDetail;
type Conversations = Awaited<ReturnType<typeof getTenantConversations>>;
type Row = Conversations["items"][number];

/**
 * Every conversation the assistant has had, and — one audited click away — what
 * was said. The list never shows a whole phone number; the runtime masks it to
 * the last four digits before it leaves the data plane.
 *
 * The list is the kit's table page (`src/features/tasks` in
 * `satnaing/shadcn-admin`): its toolbar, its faceted filters, its column
 * header, its pagination. Opening a row opens the kit's chat layout
 * (`src/features/chats`) in a sheet: the header names the caller and the
 * channel, the notes the runtime drafted sit above the messages, and the
 * messages are bubbles by role.
 */
export function ConversationsPage() {
  return (
    <OrgShell
      title="Conversations"
      description="Every call, text and chat the assistant has answered."
    >
      {(org) => <Body org={org} />}
    </OrgShell>
  );
}

const CHANNELS = ["voice", "sms", "chat", "instagram", "messenger"];

/** The three outcomes the runtime records, plus a conversation still running. */
const BANDS = [
  { value: "1", label: bandLabel(1) },
  { value: "2", label: bandLabel(2) },
  { value: "3", label: bandLabel(3) },
  { value: "0", label: bandLabel(null) },
];

/** `controller`: whether a person has taken this conversation over. */
const CONTROLLERS = ["ai", "human", "closed"].map((value) => ({
  value,
  label: controllerLabel(value),
}));

const columns: ColumnDef<Row>[] = [
  {
    id: "started",
    accessorFn: (row) => row.started_at,
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Started" />
    ),
    cell: ({ row }) => (
      <span className="whitespace-nowrap">
        {formatDateTime(row.original.started_at)}
      </span>
    ),
    enableSorting: false,
  },
  {
    id: "channel",
    accessorFn: (row) => row.channel,
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Channel" />
    ),
    cell: ({ row }) => channelLabel(row.original.channel),
    enableSorting: false,
    filterFn: (row, id, value) => (value as string[]).includes(row.getValue(id)),
  },
  {
    id: "caller",
    accessorFn: (row) => row.caller_masked ?? "",
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Caller" />
    ),
    cell: ({ row }) => (
      <span className="font-medium">{row.original.caller_masked ?? "—"}</span>
    ),
    enableSorting: false,
    enableHiding: false,
  },
  {
    id: "length",
    accessorFn: (row) => row.duration_s ?? 0,
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Length" />
    ),
    cell: ({ row }) => formatDuration(row.original.duration_s),
    enableSorting: false,
  },
  {
    id: "outcome",
    accessorFn: (row) => String(row.band ?? 0),
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Outcome" />
    ),
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <span>{bandLabel(row.original.band)}</span>
        {row.original.health_context && (
          <Badge
            variant="outline"
            data-testid="health-badge"
            className="gap-1 font-normal"
          >
            <IconHeartRateMonitor className="size-3" />
            health context
          </Badge>
        )}
      </div>
    ),
    enableSorting: false,
    filterFn: (row, id, value) => (value as string[]).includes(row.getValue(id)),
  },
  {
    id: "handled by",
    accessorFn: (row) => row.controller,
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Handled by" />
    ),
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {controllerLabel(row.original.controller)}
      </span>
    ),
    enableSorting: false,
    filterFn: (row, id, value) => (value as string[]).includes(row.getValue(id)),
  },
  {
    id: "requests",
    accessorFn: (row) => row.item_count,
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Requests" />
    ),
    cell: ({ row }) => row.original.item_count,
    enableSorting: false,
  },
];

/** The one value a faceted filter can hand the runtime, or nothing. */
function onlyValue(filters: ColumnFiltersState, id: string): string | undefined {
  const chosen = filters.find((filter) => filter.id === id)?.value as
    | string[]
    | undefined;
  return chosen && chosen.length === 1 ? chosen[0] : undefined;
}

function Body({ org }: { org: Org }) {
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState({});
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 25,
  });

  // The runtime filters by one channel and one band, and pages at its own
  // size; the table asks it for exactly that when a facet names a single
  // value. A facet with several values chosen, and the toolbar's search on the
  // caller, narrow the page that came back — the runtime has no search to ask.
  const channel = onlyValue(columnFilters, "channel");
  const band = onlyValue(columnFilters, "outcome");

  const { data, isLoading, error } = useQuery(getTenantConversations, {
    slug: org.slug,
    channel,
    band: band && band !== "0" ? Number(band) : undefined,
    page: pagination.pageIndex + 1,
  });

  const [detail, setDetail] = useState<Detail | null>(null);
  const [reading, setReading] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ message?: string } | null>(null);

  // The tenant's wording for the notes label, from the configuration the
  // settings page already reads: one request for the page, none per transcript.
  // A failure here is not shown — `notesLabel` falls back to the runtime's own
  // default rather than leaving the transcript unopenable.
  const { data: settings } = useQuery(getTenantSettings, { slug: org.slug });
  const label = notesLabel(settings?.config);

  async function open(conversationId: string) {
    setProblem(null);
    setReading(conversationId);
    try {
      // Reading a transcript is an audited act: the runtime writes the row,
      // naming the person whose session this is.
      setDetail(await readConversation({ slug: org.slug, conversationId }));
    } catch (caught) {
      setProblem(caught as { message?: string });
    } finally {
      setReading(null);
    }
  }

  // A texting number can be blocked from its own transcript (plan F). The
  // runtime refuses staff numbers and writes the audit row.
  const blockCaller =
    detail && detail.conversation.channel === "sms" && detail.conversation.caller
      ? async () => {
          await blockSmsNumber({
            slug: org.slug,
            phone: detail.conversation.caller as string,
          });
        }
      : undefined;

  // `?conversation=` is how the command palette hands this page a conversation
  // someone picked out of it. Opening one is exactly what clicking its row
  // does, audited read and all, so the deep link does the same thing once.
  const [searchParams] = useSearchParams();
  const wanted = searchParams.get("conversation");
  const opened = useRef<string | null>(null);

  useEffect(() => {
    if (!wanted || opened.current === wanted) {
      return;
    }
    opened.current = wanted;
    void open(wanted);
    // `open` is redefined on every render; the ref above is what keeps this to
    // one read per conversation, so it is deliberately not a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted]);

  const rows = useMemo(() => data?.items ?? [], [data]);
  const pageSize = data?.pageSize ?? 25;

  const table = useReactTable({
    data: rows,
    columns,
    state: { columnFilters, columnVisibility, pagination },
    // The runtime pages, not the table: a page is what it answered with.
    manualPagination: true,
    rowCount: data?.total ?? rows.length,
    onColumnFiltersChange: (updater) => {
      setColumnFilters(updater);
      // A narrowed list is a different list; page four of the old one is not
      // where anybody wanted to land.
      setPagination((current) => ({ ...current, pageIndex: 0 }));
    },
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
  });

  useEffect(() => {
    if (pagination.pageSize !== pageSize) {
      setPagination((current) => ({ ...current, pageSize }));
    }
  }, [pageSize, pagination.pageSize]);

  const visible = table.getRowModel().rows;

  return (
    <>
      <Problem error={error ?? problem} />

      <div className="flex flex-1 flex-col gap-4">
        <DataTableToolbar
          table={table}
          searchPlaceholder="Filter by caller…"
          searchKey="caller"
          filters={[
            {
              columnId: "channel",
              title: "Channel",
              options: CHANNELS.map((value) => ({
                value,
                label: channelLabel(value),
              })),
            },
            { columnId: "outcome", title: "Outcome", options: BANDS },
            {
              columnId: "handled by",
              title: "Handled by",
              options: CONTROLLERS,
            },
          ]}
        />

        <div className="overflow-hidden rounded-md border">
          <Table className="min-w-xl">
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id} colSpan={header.colSpan}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="text-muted-foreground h-24 text-center"
                  >
                    Loading…
                  </TableCell>
                </TableRow>
              ) : visible.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns.length} className="p-0">
                    <EmptyState
                      title="Nothing on this channel yet"
                      description="A call, a text or a chat lands here as soon as the assistant answers one."
                      icon={IconMessages}
                      className="border-0"
                    />
                  </TableCell>
                </TableRow>
              ) : (
                visible.map((row) => (
                  <TableRow
                    key={row.id}
                    data-testid="conversation-row"
                    className="cursor-pointer"
                    onClick={() => open(row.original.id)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        <DataTablePagination
          table={table}
          className="mt-auto"
          pageSizeOptions={[pageSize]}
        />
      </div>

      <TranscriptSheet
        detail={detail}
        label={label}
        testId="transcript-drawer"
        busy={reading !== null}
        onBlock={blockCaller}
        onClose={() => setDetail(null)}
      />
    </>
  );
}
