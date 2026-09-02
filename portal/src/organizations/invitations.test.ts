import { describe, expect, it } from "vitest";

import {
  INVITATION_LIFETIME_DAYS,
  invitationExpiryFrom,
  invitationStatus,
  isInvitedAddress,
} from "./invitations";

const NOW = new Date("2026-09-02T12:00:00Z");

describe("invitation expiry", () => {
  it("expires seven days after it is created", () => {
    expect(INVITATION_LIFETIME_DAYS).toBe(7);
    expect(invitationExpiryFrom(NOW).toISOString()).toBe(
      "2026-09-09T12:00:00.000Z",
    );
  });

  it("is pending while it is unused and unexpired", () => {
    expect(
      invitationStatus(
        { expiresAt: invitationExpiryFrom(NOW), acceptedAt: null },
        NOW,
      ),
    ).toBe("pending");
  });

  it("is expired once its expiry has passed", () => {
    const expiresAt = invitationExpiryFrom(NOW);
    const eightDaysOn = new Date("2026-09-10T12:00:00Z");

    expect(invitationStatus({ expiresAt, acceptedAt: null }, eightDaysOn)).toBe(
      "expired",
    );
  });

  it("is used once it has been accepted, so it cannot be accepted twice", () => {
    expect(
      invitationStatus(
        {
          expiresAt: invitationExpiryFrom(NOW),
          acceptedAt: new Date("2026-09-03T09:00:00Z"),
        },
        NOW,
      ),
    ).toBe("accepted");
  });
});

describe("the invited address", () => {
  it("matches regardless of case and surrounding space", () => {
    expect(isInvitedAddress("Dana@Skincentrix.ca", " dana@skincentrix.ca ")).toBe(
      true,
    );
  });

  it("does not match a different address", () => {
    expect(isInvitedAddress("dana@skincentrix.ca", "someone@else.ca")).toBe(
      false,
    );
  });

  it("does not match a missing address", () => {
    expect(isInvitedAddress("dana@skincentrix.ca", null)).toBe(false);
  });
});
