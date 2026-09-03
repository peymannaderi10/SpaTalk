import {
  IconClockHour4,
  IconGitCommit,
  IconLayersSubtract,
  IconPlayerPause,
  IconServerBolt,
  type TablerIcon,
} from "@tabler/icons-react";
import { type AuthUser } from "wasp/auth";
import { getRuntimeStatus, useQuery } from "wasp/client/operations";
import { EmptyState } from "../client/components/empty-state";
import { PageHeader } from "../client/components/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "../client/components/ui/alert";
import { Badge } from "../client/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";
import { DefaultLayout } from "./layout/DefaultLayout";

/**
 * Whether the front desk service is keeping up: how much work is queued, how
 * old the oldest queued job is, how much has been given up on, which tenants
 * it is serving and on what configuration, and which build is deployed.
 *
 * The stat cards are the kit's dashboard cards; the tenants panel is its
 * "recent" list.
 *
 * Everything on this page is the runtime's own answer to `GET /internal/health`
 * and `GET /healthz`; the portal computes nothing here.
 */
export function HealthPage({ user }: { user: AuthUser }) {
  const { data, isLoading, error } = useQuery(getRuntimeStatus);

  return (
    <DefaultLayout user={user}>
      <div className="flex flex-1 flex-col gap-4 sm:gap-6">
        <PageHeader
          title="Runtime health"
          description="What the front desk service is carrying right now."
        />

        {isLoading && (
          <p className="text-muted-foreground text-sm">Loading…</p>
        )}

        {error && (
          <Alert variant="destructive" data-testid="health-problem">
            <AlertTitle>The front desk service did not answer</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        )}

        {data && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Tile
                id="queued-jobs"
                label="Queued jobs"
                icon={IconLayersSubtract}
                value={String(data.health.queued_jobs)}
                note="waiting to run"
              />
              <Tile
                id="oldest-queued-age"
                label="Oldest queued"
                icon={IconClockHour4}
                value={
                  data.health.oldest_queued_age_s === null
                    ? "nothing queued"
                    : `${Math.round(data.health.oldest_queued_age_s)} s`
                }
                note="how long the front of the queue has waited"
              />
              <Tile
                id="dead-jobs"
                label="Given up on"
                icon={IconPlayerPause}
                value={String(data.health.dead_jobs)}
                note="jobs that ran out of retries"
              />
              <Tile
                id="commit"
                label="Deployed commit"
                icon={IconGitCommit}
                value={data.status.commit || "not recorded in this build"}
                note="what is running"
              />
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Tenants it is serving</CardTitle>
                <CardDescription>
                  Each with the configuration version it answered on.
                </CardDescription>
              </CardHeader>
              <CardContent data-testid="health-tenants">
                {data.status.tenants.length === 0 ? (
                  <EmptyState
                    title="No tenant is configured"
                    description="The service is answering but has nothing to answer for."
                    icon={IconServerBolt}
                    className="border-0"
                  />
                ) : (
                  <ul className="space-y-6">
                    {data.status.tenants.map((tenant) => (
                      <li key={tenant} className="flex items-center gap-4">
                        <span className="bg-muted text-muted-foreground flex size-9 shrink-0 items-center justify-center rounded-full">
                          <IconServerBolt className="size-4" />
                        </span>
                        <div className="flex flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">
                          <span className="text-sm leading-none font-medium">
                            {tenant}
                          </span>
                          <Badge
                            variant="outline"
                            data-testid={`health-tenant-version-${tenant}`}
                            className="font-normal"
                          >
                            configuration v
                            {data.status.config_versions[tenant] ?? "unknown"}
                          </Badge>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </DefaultLayout>
  );
}

function Tile({
  id,
  label,
  value,
  note,
  icon: Icon,
}: {
  id: string;
  label: string;
  value: string;
  note: string;
  icon: TablerIcon;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="text-muted-foreground size-4" />
      </CardHeader>
      <CardContent>
        <div
          data-testid={`health-${id}`}
          className="truncate text-xl font-bold"
        >
          {value}
        </div>
        <p className="text-muted-foreground text-xs">{note}</p>
      </CardContent>
    </Card>
  );
}
