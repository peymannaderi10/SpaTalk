import {
  IconAlertTriangle,
  IconBolt,
  IconClipboardList,
  IconClock,
  IconCoin,
  IconMessage,
  IconMessageChatbot,
  IconPhone,
  type TablerIcon,
} from "@tabler/icons-react";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { formatCad, formatMinutes } from "./formatting";

/**
 * The row of stat cards at the top of a clinic's overview, decided away from
 * the markup so who sees which card is a thing a test can read.
 *
 * Two cards are not for the clinic. "Estimated cost" is what the providers
 * charged the *agency* to answer this phone — a cost of goods, not a bill, and
 * an order of magnitude below what the clinic pays. "Reply time" is the
 * agency's engineering figure. Both are on the page for an agency admin and
 * never for a clinic user. Who is an admin is `viewerIsAgencyAdmin`, which the
 * server puts in `getTenantOverview`'s answer; a client-side guess about who is
 * looking would be a guess.
 *
 * Everything else on the row is the clinic's own: its calls, its minutes, its
 * open work.
 */

export type OverviewTile = {
  id: string;
  label: string;
  value: string;
  note: string;
  icon: TablerIcon;
};

/** As much of `getTenantOverview`'s answer as the cards read. */
export type OverviewCards = {
  viewerIsAgencyAdmin: boolean;
  month: {
    totals: {
      calls: number;
      call_minutes: number;
      sms_in: number;
      sms_out: number;
      chats: number;
      est_cost_cad: number;
    };
  };
  health: { open_items: number; overdue_items: number };
  latency: { p95_ms: number }[];
};

export function overviewTiles(data: OverviewCards): OverviewTile[] {
  const { totals } = data.month;
  const latest = data.latency[data.latency.length - 1];

  const tiles: OverviewTile[] = [
    {
      id: "calls",
      label: "Calls",
      icon: IconPhone,
      value: String(totals.calls),
      note: "answered this month",
    },
    {
      id: "call-minutes",
      label: "Call minutes",
      icon: IconClock,
      value: formatMinutes(totals.call_minutes),
      note: "on the phone this month",
    },
    {
      id: "texts",
      label: "Texts",
      icon: IconMessage,
      value: String(totals.sms_in + totals.sms_out),
      note: "sent and received",
    },
    {
      id: "chats",
      label: "Chats",
      icon: IconMessageChatbot,
      value: String(totals.chats),
      note: "web and social conversations",
    },
    {
      id: "open-items",
      label: "Open requests",
      icon: IconClipboardList,
      value: String(data.health.open_items),
      note: "waiting on the team",
    },
    {
      id: "overdue-items",
      label: "Overdue",
      icon: IconAlertTriangle,
      value: String(data.health.overdue_items),
      note: "past the promised time",
    },
  ];

  if (data.viewerIsAgencyAdmin) {
    tiles.push(
      {
        id: "p95-latency",
        label: "Reply time (p95)",
        icon: IconBolt,
        value: latest ? `${latest.p95_ms} ms` : "—",
        note: "nineteen replies in twenty are faster",
      },
      {
        id: "est-cost",
        label: "Estimated cost",
        icon: IconCoin,
        value: formatCad(totals.est_cost_cad),
        note: "what the providers charged us",
      },
    );
  }

  return tiles;
}

/** The cards themselves, in the kit's dashboard row. */
export function OverviewTiles({ tiles }: { tiles: OverviewTile[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Tile key={tile.id} tile={tile} />
      ))}
    </div>
  );
}

function Tile({ tile }: { tile: OverviewTile }) {
  const Icon = tile.icon;
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{tile.label}</CardTitle>
        <Icon className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div data-testid={`tile-${tile.id}`} className="text-2xl font-bold">
          {tile.value}
        </div>
        <p className="text-muted-foreground text-xs">{tile.note}</p>
      </CardContent>
    </Card>
  );
}
