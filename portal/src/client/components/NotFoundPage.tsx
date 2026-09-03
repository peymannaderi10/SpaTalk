import { useNavigate } from "react-router";
import { useAuth } from "wasp/client/auth";
import { Link as WaspRouterLink, routes } from "wasp/client/router";
import { Button } from "./ui/button";

/**
 * The kit's not-found page (`src/features/errors/not-found-error.tsx` in
 * `satnaing/shadcn-admin`): the number, the line, and the two ways out.
 *
 * "Home" is where this person actually belongs — their organisations if they
 * are signed in, the front door if they are not.
 */
export function NotFoundPage() {
  const { data: user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="h-svh">
      <div className="m-auto flex h-full w-full flex-col items-center justify-center gap-2">
        <h1 className="text-[7rem] leading-tight font-bold">404</h1>
        <span className="font-medium">This page does not exist</span>
        <p className="text-muted-foreground text-center">
          The address may have changed, or it was never a page here.
        </p>
        <div className="mt-6 flex gap-4">
          <Button variant="outline" onClick={() => navigate(-1)}>
            Go back
          </Button>
          <Button asChild>
            <WaspRouterLink
              to={user ? routes.AppRoute.to : routes.RootRoute.to}
            >
              {user ? "Your organisations" : "Back home"}
            </WaspRouterLink>
          </Button>
        </div>
      </div>
    </div>
  );
}
