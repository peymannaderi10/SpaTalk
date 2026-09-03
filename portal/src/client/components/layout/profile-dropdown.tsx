import { IconLogout, type TablerIcon } from "@tabler/icons-react";
import { Link } from "react-router";

import { Avatar, AvatarFallback, AvatarImage } from "../ui/avatar";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

/**
 * Adapted from `satnaing/shadcn-admin` (`src/components/profile-dropdown.tsx`).
 *
 * The kit hard-codes one demo user and a fixed list of links, and its sign-out
 * goes through a confirmation dialog wired to Clerk. Here the person, the
 * links and the sign-out are props, so the shell can hand it whatever the
 * portal's own user menu holds without this file importing Wasp. The kit's
 * TanStack `Link` is react-router's.
 */
export type ProfileMenuItem = {
  label: string;
  to: string;
  icon?: TablerIcon;
};

export function ProfileDropdown({
  name,
  email,
  avatarUrl,
  items = [],
  onSignOut,
}: {
  name: string;
  email?: string | null;
  avatarUrl?: string | null;
  items?: ProfileMenuItem[];
  onSignOut: () => void;
}) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="relative h-8 w-8 rounded-full"
          data-testid="profile-menu"
        >
          <Avatar className="h-8 w-8">
            {avatarUrl && <AvatarImage src={avatarUrl} alt={name} />}
            <AvatarFallback>{initials(name)}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-1.5">
            <p className="text-sm leading-none font-medium">{name}</p>
            {email && (
              <p className="text-muted-foreground text-xs leading-none">
                {email}
              </p>
            )}
          </div>
        </DropdownMenuLabel>
        {items.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {items.map((item) => (
                <DropdownMenuItem key={item.to} asChild>
                  <Link to={item.to}>
                    {item.icon && <item.icon />}
                    {item.label}
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onClick={onSignOut}
          data-testid="sign-out"
        >
          <IconLogout />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** First letter of the first word and of the last, so an avatar always says something. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
