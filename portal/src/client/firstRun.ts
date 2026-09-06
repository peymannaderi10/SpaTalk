/**
 * The "Getting set up" checklist on a clinic's overview (onboarding roadmap,
 * section 4): what is left before the assistant takes real calls, each step
 * linking to where it is done, and the whole card gone once the first tracked
 * request lands.
 *
 * The facts are the runtime's own: the configuration as `GET
 * /internal/tenants/{id}/config` serves it, the numbers the agency mapped,
 * and whether a conversation or a request exists yet. This module only reads
 * them, and reads them tolerantly, because the configuration is JSON the
 * runtime owns and a field may be absent on an older version.
 */

export const FIRST_RUN_KEYS = [
  "number",
  "hours",
  "services",
  "team",
  "knowledge",
  "delivery",
  "conversation",
  "request",
] as const;

export type FirstRunKey = (typeof FIRST_RUN_KEYS)[number];

export type FirstRunStep = {
  key: FirstRunKey;
  label: string;
  done: boolean;
  /** Where the step is done, as a path under the portal. */
  to: string;
};

/** As much of the tenant configuration as the checklist reads; every field may be missing. */
export type FirstRunConfig = {
  hours?: Record<string, unknown[]> | null;
  services?: unknown[] | null;
  team?: unknown[] | null;
  knowledge?: string | null;
  faq?: unknown[] | null;
  delivery?: {
    destinations?:
      | {
          kind?: string;
          address?: string | null;
          address_env?: string | null;
        }[]
      | null;
  } | null;
};

export type FirstRunFacts = {
  slug: string;
  numbers: { number: string; kind: string }[];
  config: FirstRunConfig;
  hadConversation: boolean;
  hadRequest: boolean;
};

/**
 * What counts as knowledge written by the clinic. The runtime's starter
 * skeleton is about six hundred characters of headings and generic lines, so
 * a page of the clinic's own facts, or one FAQ entry, is what ticks the step.
 */
export const KNOWLEDGE_MIN_CHARS = 1000;

function nonEmpty(value: string | null | undefined): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

/** A destination a request can reach a person through: email, or the staff SMS. */
function reachesStaff(destination: {
  kind?: string;
  address?: string | null;
  address_env?: string | null;
}): boolean {
  if (destination.kind === "email") {
    return nonEmpty(destination.address) || nonEmpty(destination.address_env);
  }
  if (destination.kind === "sms") {
    return nonEmpty(destination.address_env);
  }
  return false;
}

export function firstRunSteps(facts: FirstRunFacts): FirstRunStep[] {
  const base = `/app/${facts.slug}`;
  const config = facts.config ?? {};
  const hours = config.hours ?? {};
  const destinations = config.delivery?.destinations ?? [];
  const knowledge = (config.knowledge ?? "").trim();

  const done: Record<FirstRunKey, boolean> = {
    number: facts.numbers.some((entry) => entry.kind === "voice"),
    hours: Object.values(hours).some(
      (spans) => Array.isArray(spans) && spans.length > 0,
    ),
    services: (config.services?.length ?? 0) > 0,
    team: (config.team?.length ?? 0) > 0,
    knowledge:
      knowledge.length >= KNOWLEDGE_MIN_CHARS || (config.faq?.length ?? 0) > 0,
    delivery: destinations.some(reachesStaff),
    conversation: facts.hadConversation,
    request: facts.hadRequest,
  };

  const steps: Omit<FirstRunStep, "done">[] = [
    {
      key: "number",
      label: "A phone number is assigned to the clinic",
      to: `${base}/settings?tab=numbers`,
    },
    {
      key: "hours",
      label: "Opening hours are set",
      to: `${base}/settings?tab=hours`,
    },
    {
      key: "services",
      label: "At least one service is listed",
      to: `${base}/settings?tab=services`,
    },
    {
      key: "team",
      label: "At least one team member is named",
      to: `${base}/settings?tab=team`,
    },
    {
      key: "knowledge",
      label: "The knowledge page or the FAQ is filled in",
      to: `${base}/settings?tab=knowledge`,
    },
    {
      key: "delivery",
      label: "Requests reach the team: a staff email or text",
      to: `${base}/settings?tab=delivery`,
    },
    {
      key: "conversation",
      label: "A test call, text or chat has happened",
      to: `${base}/conversations`,
    },
    {
      key: "request",
      label: "The first request has landed",
      to: `${base}/requests`,
    },
  ];

  return steps.map((step) => ({ ...step, done: done[step.key] }));
}

/** The card's own end: it goes once the first tracked request exists. */
export function firstRunDone(facts: FirstRunFacts): boolean {
  return facts.hadRequest;
}
