/**
 * An invitation opened while signed out has to survive the trip through
 * signup and email verification, so the token is parked in the browser until
 * the person comes back signed in.
 */

const STORAGE_KEY = "spatalk:pendingInvitation";

export function rememberPendingInvitation(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // A browser with storage disabled simply loses the shortcut: the link in
    // the invitation email still works.
  }
}

export function readPendingInvitation(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function forgetPendingInvitation(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to forget if storage is unavailable.
  }
}

export function invitationPath(token: string): string {
  return `/invite/${encodeURIComponent(token)}`;
}
