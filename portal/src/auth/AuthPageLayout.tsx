import { ReactNode } from "react";
import { BRAND } from "../client/brand";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../client/components/ui/card";

/**
 * The frame every signed-out page sits in, from the kit
 * (`src/features/auth/auth-layout.tsx` and `src/features/auth/sign-in` in
 * `satnaing/shadcn-admin`): the mark and the product's name centred above a
 * card that holds the form, with a line of small print under it.
 *
 * The name, the mark and the tagline come from `BRAND`, so a rename is one
 * file.
 *
 * The card's title is a real heading rather than the kit's `div`, because the
 * Playwright suite reads a page by the heading it opens with.
 */
export function AuthPageLayout({
  title,
  description,
  footer,
  children,
}: {
  title: string;
  description?: ReactNode;
  /** The small print under the card: the way to the other auth pages. */
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="container grid h-svh max-w-none items-center justify-center">
      <div className="mx-auto flex w-full flex-col justify-center space-y-2 py-8 sm:p-8">
        <div className="mb-4 flex items-center justify-center">
          <img src={BRAND.logo.mark} alt="" className="me-2 size-8" />
          <h1 className="text-xl font-medium">{BRAND.name}</h1>
        </div>

        <Card className="gap-4 sm:min-w-sm">
          <CardHeader>
            <CardTitle className="text-lg tracking-tight">
              <h2>{title}</h2>
            </CardTitle>
            <CardDescription>{description ?? BRAND.tagline}</CardDescription>
          </CardHeader>
          <CardContent>{children}</CardContent>
          {footer && (
            <CardFooter>
              <p className="text-muted-foreground mx-auto px-8 text-center text-sm text-balance">
                {footer}
              </p>
            </CardFooter>
          )}
        </Card>
      </div>
    </div>
  );
}
