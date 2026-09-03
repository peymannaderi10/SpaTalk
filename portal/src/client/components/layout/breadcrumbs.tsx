import { Fragment } from "react";
import { Link } from "react-router";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "../ui/breadcrumb";

/**
 * The kit shows the page's place in the app as a heading above the content;
 * this portal wants it in the header, so the crumbs are built here on the
 * registry's `breadcrumb` primitives rather than copied from the kit, which
 * has no breadcrumb component of its own.
 *
 * The trail is data, not a route parse: the caller knows what the page is
 * about — an organisation, a request number — and the shell should not have to
 * guess it back out of the URL.
 */
export type Crumb = {
  label: string;
  /** Omitted for the last crumb, which is the page you are on. */
  to?: string;
};

export function Breadcrumbs({
  items,
  className,
}: {
  items: Crumb[];
  className?: string;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <Breadcrumb className={className}>
      <BreadcrumbList>
        {items.map((crumb, index) => {
          const isLast = index === items.length - 1;
          return (
            <Fragment key={`${crumb.label}-${index}`}>
              <BreadcrumbItem
                className={isLast ? undefined : "hidden md:block"}
              >
                {crumb.to && !isLast ? (
                  <BreadcrumbLink asChild>
                    <Link to={crumb.to}>{crumb.label}</Link>
                  </BreadcrumbLink>
                ) : (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                )}
              </BreadcrumbItem>
              {!isLast && <BreadcrumbSeparator className="hidden md:block" />}
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
