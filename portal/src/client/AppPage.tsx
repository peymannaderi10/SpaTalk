import { type AuthUser } from "wasp/auth";

/**
 * Placeholder shell for the client app.
 * The organisation switcher and the per-organisation pages replace this body.
 */
export function AppPage({ user }: { user: AuthUser }) {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-foreground text-2xl font-semibold">Your front desk</h1>
      <p className="text-muted-foreground mt-4 text-sm">
        Signed in as {user.email ?? user.id}.
      </p>
      <p className="text-muted-foreground mt-2 text-sm">
        Conversations, requests, usage and settings appear here once an
        organisation is connected to a runtime tenant.
      </p>
    </main>
  );
}
