import { useLocation, useNavigate } from "react-router";
import { listMyOrganizations, useQuery } from "wasp/client/operations";

/**
 * The current organisation lives in the URL (`/app/:orgSlug/...`), so the
 * switcher is a jump list: pick an organisation, land on its pages.
 */
export function OrgSwitcher() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: organizations } = useQuery(listMyOrganizations);

  if (!organizations || organizations.length === 0) {
    return null;
  }

  const currentSlug = currentOrgSlug(location.pathname);

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">Organisation</span>
      <select
        aria-label="Organisation"
        className="border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm"
        value={currentSlug ?? ""}
        onChange={(event) => {
          const slug = event.target.value;
          if (slug) {
            navigate(`/app/${slug}`);
          }
        }}
      >
        <option value="" disabled>
          Choose an organisation
        </option>
        {organizations.map((org) => (
          <option key={org.id} value={org.slug}>
            {org.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function currentOrgSlug(pathname: string): string | null {
  const match = pathname.match(/^\/app\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}
