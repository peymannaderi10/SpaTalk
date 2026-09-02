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
  return (
    <div data-testid="config-versions" className="space-y-3 text-sm">
      <p className="text-muted-foreground">
        Every save is a version. Rolling back adds a new version equal to the
        one you choose; nothing is removed.
      </p>
      <table className="w-full text-left">
        <thead className="text-muted-foreground">
          <tr>
            <th className="py-2 font-normal">Version</th>
            <th className="py-2 font-normal">Saved</th>
            <th className="py-2 font-normal">By</th>
            <th className="py-2 font-normal"></th>
          </tr>
        </thead>
        <tbody>
          {versions.map((version) => (
            <tr key={version.version} className="border-border border-t">
              <td className="py-2">
                Version {version.version}
                {version.version === current && " (current)"}
              </td>
              <td className="py-2">{formatDateTime(version.created_at)}</td>
              <td className="py-2">{version.created_by}</td>
              <td className="py-2 text-right">
                {canRollBack && version.version !== current && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    data-testid={`rollback-${version.version}`}
                    onClick={() => onRollBack(version.version)}
                  >
                    Roll back
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
