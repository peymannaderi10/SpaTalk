import { type ColumnDef } from "@tanstack/react-table";

import { DataTable } from "../components/data-table";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { formatDateTime } from "../formatting";

export type ConfigVersion = {
  version: number;
  created_by: string;
  created_at: string;
};

/**
 * Nothing is ever deleted: rolling back writes a *new* version equal to the old
 * one, so the history stays a history.
 *
 * The kit's data table, small: the history is short and nobody filters it.
 */
export function VersionsPanel({
  versions,
  current,
  canRollBack,
  busy,
  onRollBack,
}: {
  versions: ConfigVersion[];
  current: number;
  canRollBack: boolean;
  busy: boolean;
  onRollBack: (version: number) => void;
}) {
  const columns: ColumnDef<ConfigVersion>[] = [
    {
      id: "version",
      accessorFn: (row) => row.version,
      header: "Version",
      cell: ({ row }) => (
        <span className="flex items-center gap-2">
          <span className="font-medium">Version {row.original.version}</span>
          {row.original.version === current && (
            <Badge variant="secondary" className="font-normal">
              current
            </Badge>
          )}
        </span>
      ),
    },
    {
      id: "saved",
      accessorFn: (row) => row.created_at,
      header: "Saved",
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "by",
      accessorFn: (row) => row.created_by,
      header: "By",
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.created_by}</span>
      ),
    },
    {
      id: "actions",
      cell: ({ row }) => (
        <div className="text-right">
          {canRollBack && row.original.version !== current && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              data-testid={`rollback-${row.original.version}`}
              onClick={() => onRollBack(row.original.version)}
            >
              Roll back
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div data-testid="config-versions" className="space-y-3 text-sm">
      <p className="text-muted-foreground">
        Every save is a version. Rolling back adds a new version equal to the
        one you choose; nothing is removed.
      </p>
      <DataTable
        columns={columns}
        data={versions}
        toolbar={false}
        pagination={false}
        testId="config-version"
        empty="No version has been saved yet."
      />
    </div>
  );
}
