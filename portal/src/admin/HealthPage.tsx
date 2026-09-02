import { type AuthUser } from "wasp/auth";
import { getRuntimeStatus, useQuery } from "wasp/client/operations";
import { DefaultLayout } from "./layout/DefaultLayout";

/**
 * Whether the front desk service is keeping up: how much work is queued, how
 * old the oldest queued job is, how much has been given up on, which tenants
 * it is serving and on what configuration, and which build is deployed.
 *
 * Everything on this page is the runtime's own answer to `GET /internal/health`
 * and `GET /healthz`; the portal computes nothing here.
 */
export function HealthPage({ user }: { user: AuthUser }) {
  const { data, isLoading, error } = useQuery(getRuntimeStatus);

  return (
    <DefaultLayout user={user}>
      <h1 className="text-foreground text-2xl font-semibold">Runtime health</h1>

      {isLoading && (
        <p className="text-muted-foreground mt-6 text-sm">Loading…</p>
      )}

      {error && (
        <p
          data-testid="health-problem"
          className="border-border text-foreground mt-6 rounded-md border p-4 text-sm"
        >
          {error.message}
        </p>
      )}

      {data && (
        <>
          <dl className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Tile
              id="queued-jobs"
              label="Queued jobs"
              value={String(data.health.queued_jobs)}
            />
            <Tile
              id="oldest-queued-age"
              label="Oldest queued"
              value={
                data.health.oldest_queued_age_s === null
                  ? "nothing queued"
                  : `${Math.round(data.health.oldest_queued_age_s)} s`
              }
            />
            <Tile
              id="dead-jobs"
              label="Given up on"
              value={String(data.health.dead_jobs)}
            />
            <Tile
              id="commit"
              label="Deployed commit"
              value={data.status.commit || "not recorded in this build"}
            />
          </dl>

          <section className="mt-10">
            <h2 className="text-foreground text-lg font-medium">
              Tenants it is serving
            </h2>
            <ul data-testid="health-tenants" className="mt-3 space-y-2 text-sm">
              {data.status.tenants.map((tenant) => (
                <li
                  key={tenant}
                  className="border-border flex items-baseline justify-between gap-4 rounded-md border p-3"
                >
                  <span className="text-foreground">{tenant}</span>
                  <span
                    data-testid={`health-tenant-version-${tenant}`}
                    className="text-muted-foreground"
                  >
                    configuration v
                    {data.status.config_versions[tenant] ?? "unknown"}
                  </span>
                </li>
              ))}
            </ul>
            {data.status.tenants.length === 0 && (
              <p className="text-muted-foreground mt-3 text-sm">
                The service is answering but has no tenants configured.
              </p>
            )}
          </section>
        </>
      )}
    </DefaultLayout>
  );
}

function Tile({
  id,
  label,
  value,
}: {
  id: string;
  label: string;
  value: string;
}) {
  return (
    <div className="border-border rounded-lg border p-4">
      <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
      <dd
        data-testid={`health-${id}`}
        className="text-foreground mt-1 text-xl font-semibold"
      >
        {value}
      </dd>
    </div>
  );
}
