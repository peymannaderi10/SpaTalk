/**
 * What a client costs the agency, and what to quote them for it.
 *
 * This is a port of `docs/research/costmodel.py`, function for function, so an
 * admin can put a client's volumes into a page instead of editing a Python
 * file. The rates it works from are never copied here: the runtime serves the
 * one rates file at `GET /internal/rates` (and `runtime/spatalk/rates.json` is
 * pinned equal to `docs/research/rates.json` by a runtime test), so the page
 * quotes against the same prices that produce every `est_cost_cad`.
 *
 * Browser-safe on purpose, in the shape of `agency.ts`: the server operation
 * fetches the rates and the page does the arithmetic, and `pricing.test.ts`
 * holds both to the Python's own printed figures.
 *
 * Provider rates are in USD; every figure this module hands out for display is
 * Canadian, converted with the file's `usd_to_cad`.
 */

// --- the rates file, as much of it as a quote reads ------------------------

export type Telephony = {
  inbound_per_min: number;
  stream_per_min?: number;
  record_per_min?: number;
};

export type Stt = { per_min: number };
export type Tts = { per_1m_chars: number };

/** USD per million tokens, in the three shapes a turn is billed in. */
export type Llm = { in: number; cached_in: number; out: number };

export type Sms = {
  out_per_msg: number;
  carrier_out_per_msg: number;
  in_per_msg: number;
  carrier_in_per_msg: number;
};

/** `rates.assumptions`: the shape of one call, and of one model turn. */
export type CallAssumptions = {
  avg_call_minutes: number;
  agent_speaking_fraction: number;
  chars_per_spoken_minute: number;
  turns_per_minute: number;
  input_tokens_uncached_per_turn: number;
  input_tokens_cached_per_turn: number;
  output_tokens_per_turn: number;
};

/** `rates.assumptions_text`: the shape of one text conversation. */
export type TextAssumptions = {
  turns_per_conversation: number;
  outbound_msgs: number;
  inbound_msgs: number;
};

/** `rates.assumptions_volume`: a month at one clinic, as the brief assumes it. */
export type VolumeAssumptions = {
  calls_per_month: number;
  sms_convs_per_month: number;
  chat_convs_per_month: number;
  outbound_msgs_per_month: number;
};

export type VoiceStack = {
  tel: string;
  stt: string;
  tts: string;
  llm: string;
  recommended?: boolean;
};

export type TextStack = { sms: string; llm: string; recommended?: boolean };

/**
 * What actually runs in production, named in the rates file itself.
 *
 * The candidate stacks above are the September research; this is the one the
 * clinics are being answered on, and it is the only one the quote prices. Each
 * field is a key into the section of the same name.
 */
export type LiveStackRef = {
  label: string;
  tel: string;
  stt: string;
  tts: string;
  llm: string;
  sms: string;
};

/** The same stack with its rates read out of the file. */
export type LiveStack = {
  label: string;
  tel: Telephony;
  stt: Stt;
  tts: Tts;
  llm: Llm;
  sms: Sms;
};

export type RatesFile = {
  usd_to_cad: number;
  /** Where the exchange rate came from, printed in the page's footnote. */
  _fx_source?: string;
  assumptions: CallAssumptions;
  assumptions_text: TextAssumptions;
  assumptions_volume: VolumeAssumptions;
  per_tenant_fixed_cad: number;
  telephony: Record<string, Telephony>;
  stt: Record<string, Stt>;
  tts: Record<string, Tts>;
  llm: Record<string, Llm>;
  sms: Record<string, Sms>;
  live_stack: LiveStackRef;
  /** The September research, kept in the file; nothing prices against them. */
  voice_stacks: Record<string, VoiceStack>;
  text_stacks: Record<string, TextStack>;
  /** Bills of materials for the platform, keyed by a client count: "1", "10", "25". */
  fixed_cad: Record<string, Record<string, number>>;
};

/** Both assumption blocks a text conversation needs: the turn and the length. */
export type ConversationAssumptions = {
  turn: CallAssumptions;
  text: TextAssumptions;
};

export function conversationAssumptions(
  rates: RatesFile,
): ConversationAssumptions {
  return { turn: rates.assumptions, text: rates.assumptions_text };
}

// --- the model itself, in USD ----------------------------------------------

/** `llm_cost_per_turn`: the dynamic part, the cached part and the reply. */
export function llmPerTurn(llm: Llm, assumptions: CallAssumptions): number {
  return (
    (assumptions.input_tokens_uncached_per_turn * llm.in +
      assumptions.input_tokens_cached_per_turn * llm.cached_in +
      assumptions.output_tokens_per_turn * llm.out) /
    1e6
  );
}

export type VoiceMinute = {
  tel: number;
  stt: number;
  tts: number;
  llm: number;
  totalUsd: number;
};

/** `voice_per_minute`: one minute of wall-clock on the phone, all four vendors. */
export function voicePerMinute(
  tel: Telephony,
  stt: Stt,
  tts: Tts,
  llm: Llm,
  assumptions: CallAssumptions,
): VoiceMinute {
  const telephony =
    tel.inbound_per_min + (tel.stream_per_min ?? 0) + (tel.record_per_min ?? 0);
  const speech =
    (assumptions.agent_speaking_fraction *
      assumptions.chars_per_spoken_minute *
      tts.per_1m_chars) /
    1e6;
  const model = assumptions.turns_per_minute * llmPerTurn(llm, assumptions);

  return {
    tel: telephony,
    stt: stt.per_min,
    tts: speech,
    llm: model,
    totalUsd: telephony + stt.per_min + speech + model,
  };
}

export type TextConversationCost = {
  llm: number;
  msgs: number;
  totalUsd: number;
};

/**
 * `text_conversation`: one back-and-forth. A web chat costs the model and
 * nothing else — there is no carrier in it — which is why the channel is an
 * argument rather than two functions.
 */
export function textConversation(
  sms: Sms,
  llm: Llm,
  channel: "sms" | "chat",
  assumptions: ConversationAssumptions,
): TextConversationCost {
  const model =
    assumptions.text.turns_per_conversation * llmPerTurn(llm, assumptions.turn);
  const msgs =
    channel === "sms"
      ? assumptions.text.outbound_msgs *
          (sms.out_per_msg + sms.carrier_out_per_msg) +
        assumptions.text.inbound_msgs *
          (sms.in_per_msg + sms.carrier_in_per_msg)
      : 0;

  return { llm: model, msgs, totalUsd: model + msgs };
}

/** `outbound_message`: one SMS the clinic sends, with the carrier's fee on it. */
export function outboundMessage(sms: Sms): { totalUsd: number } {
  return { totalUsd: sms.out_per_msg + sms.carrier_out_per_msg };
}

// --- the platform's own bill ------------------------------------------------

function sumOf(bom: Record<string, number>): number {
  return Object.values(bom).reduce((total, line) => total + line, 0);
}

/**
 * What the platform costs per month at a given number of clients, in CAD (this
 * block of the rates file is already Canadian).
 *
 * The tiers are bills of materials keyed by a client count — "1", "10", "25".
 * An exact key wins; otherwise the highest tier at or below the count does,
 * which is what `costmodel.py` picks, and a count below the smallest tier gets
 * the smallest tier rather than nothing.
 */
export function fixedPlatformCad(
  fixedCad: Record<string, Record<string, number>>,
  clients: number,
): number {
  const exact = fixedCad[String(clients)];
  if (exact) {
    return sumOf(exact);
  }

  const tiers = Object.keys(fixedCad)
    .map((key) => Number(key))
    .filter((tier) => Number.isFinite(tier));
  if (tiers.length === 0) {
    return 0;
  }

  const atOrBelow = tiers.filter((tier) => tier <= clients);
  const chosen =
    atOrBelow.length > 0 ? Math.max(...atOrBelow) : Math.min(...tiers);
  return sumOf(fixedCad[String(chosen)] ?? {});
}

// --- margin, which is margin and not markup --------------------------------

/** The founder's default: 65% margin means the cost is 35% of the price. */
export const DEFAULT_MARGIN = 0.65;

/** The founder's default: one clinic carrying the platform's fixed cost. */
export const DEFAULT_CLIENTS = 1;

/**
 * A margin of exactly one would price a cost at infinity, so the model keeps a
 * hair under it. Anything that is not a number at all falls back to the
 * default rather than quietly becoming zero.
 */
export function clampMargin(margin: number): number {
  if (!Number.isFinite(margin)) {
    return DEFAULT_MARGIN;
  }
  return Math.min(Math.max(margin, 0), 0.99);
}

/** `price = cost / (1 - margin)`. */
export function priceAtMargin(cogsCad: number, margin: number): number {
  return cogsCad / (1 - clampMargin(margin));
}

/**
 * The margin a given price would carry at a given cost, or nothing when there
 * is no price to take a margin on.
 */
export function marginOf(cogsCad: number, priceCad: number): number | null {
  if (!Number.isFinite(priceCad) || priceCad <= 0) {
    return null;
  }
  return (priceCad - cogsCad) / priceCad;
}

// --- the quote --------------------------------------------------------------

export type QuoteInputs = {
  /** How many clients share the platform's fixed cost. */
  clients: number;
  /** As a fraction: 0.65 is 65%. */
  margin: number;
  callsPerMonth: number;
  avgCallMinutes: number;
  smsConvsPerMonth: number;
  chatConvsPerMonth: number;
  outboundMsgsPerMonth: number;
};

/** One line of the monthly cost of goods, in CAD. */
export type QuoteLine = { id: string; label: string; cad: number };

export type Quote = {
  breakdown: QuoteLine[];
  /** What the month costs the agency, in CAD. */
  cogsCad: number;
  /** What to charge for it at the chosen margin, in CAD. */
  priceCad: number;
  perCall: number;
  perMinute: number;
  perTextConv: number;
  perChatConv: number;
  perOutboundMsg: number;
  /** The same four units at the chosen margin: what one of each is worth. */
  unitPrices: {
    perCall: number;
    perMinute: number;
    perTextConv: number;
    perChatConv: number;
  };
  /** The stack these figures priced, for the page's footnote. */
  stackLabel: string;
};

function vendor<T>(
  section: Record<string, T> | undefined,
  key: string,
  what: string,
): T {
  const found = section?.[key];
  if (!found) {
    throw new Error(
      `The rates file names ${key} as the live stack's ${what}, and has no such entry.`,
    );
  }
  return found;
}

/**
 * The production stack with its rates attached. A stack naming something the
 * file does not hold is refused rather than quietly priced at nothing.
 */
export function liveStack(rates: RatesFile): LiveStack {
  const ref = rates.live_stack;
  if (!ref) {
    throw new Error("The rates file names no live stack, so there is nothing to price.");
  }
  return {
    label: ref.label,
    tel: vendor(rates.telephony, ref.tel, "tel"),
    stt: vendor(rates.stt, ref.stt, "stt"),
    tts: vendor(rates.tts, ref.tts, "tts"),
    llm: vendor(rates.llm, ref.llm, "llm"),
    sms: vendor(rates.sms, ref.sms, "sms"),
  };
}

/**
 * Where the form starts: the volumes and the call length the rates file states,
 * and the founder's margin and client count — or the ones this browser last
 * remembered. There is no stack to choose: the quote prices what is running.
 */
export function defaultInputs(
  rates: RatesFile,
  assumptions: StoredAssumptions = {
    margin: DEFAULT_MARGIN,
    clients: DEFAULT_CLIENTS,
  },
): QuoteInputs {
  const volume = rates.assumptions_volume;
  return {
    clients: assumptions.clients,
    margin: assumptions.margin,
    callsPerMonth: volume.calls_per_month,
    avgCallMinutes: rates.assumptions.avg_call_minutes,
    smsConvsPerMonth: volume.sms_convs_per_month,
    chatConvsPerMonth: volume.chat_convs_per_month,
    outboundMsgsPerMonth: volume.outbound_msgs_per_month,
  };
}

/**
 * The month, priced. Six lines of cost of goods — the four variable ones, the
 * numbers this client needs of its own, and its share of the platform — then
 * the price that carries the chosen margin over the lot.
 */
export function quote(inputs: QuoteInputs, rates: RatesFile): Quote {
  const stack = liveStack(rates);
  const fx = rates.usd_to_cad;
  const conversation = conversationAssumptions(rates);
  const messaging = stack.sms;
  const textModel = stack.llm;

  const perMinute =
    voicePerMinute(
      stack.tel,
      stack.stt,
      stack.tts,
      stack.llm,
      rates.assumptions,
    ).totalUsd * fx;
  const perCall = perMinute * inputs.avgCallMinutes;
  const perTextConv =
    textConversation(messaging, textModel, "sms", conversation).totalUsd * fx;
  const perChatConv =
    textConversation(messaging, textModel, "chat", conversation).totalUsd * fx;
  const perOutboundMsg = outboundMessage(messaging).totalUsd * fx;

  const clients = Math.max(1, Math.floor(inputs.clients) || 1);
  const breakdown: QuoteLine[] = [
    {
      id: "voice",
      label: "Calls",
      cad: inputs.callsPerMonth * perCall,
    },
    {
      id: "sms",
      label: "SMS conversations",
      cad: inputs.smsConvsPerMonth * perTextConv,
    },
    {
      id: "chat",
      label: "Chat conversations",
      cad: inputs.chatConvsPerMonth * perChatConv,
    },
    {
      id: "outbound",
      label: "Outbound messages",
      cad: inputs.outboundMsgsPerMonth * perOutboundMsg,
    },
    {
      id: "per-tenant-fixed",
      label: "Numbers and other per-client fixed cost",
      cad: rates.per_tenant_fixed_cad,
    },
    {
      id: "platform-share",
      label: `Share of the platform, split ${clients} way${clients === 1 ? "" : "s"}`,
      cad: fixedPlatformCad(rates.fixed_cad, clients) / clients,
    },
  ];

  const cogsCad = breakdown.reduce((total, line) => total + line.cad, 0);
  const atMargin = (cost: number) => priceAtMargin(cost, inputs.margin);

  return {
    breakdown,
    cogsCad,
    priceCad: atMargin(cogsCad),
    perCall,
    perMinute,
    perTextConv,
    perChatConv,
    perOutboundMsg,
    unitPrices: {
      perCall: atMargin(perCall),
      perMinute: atMargin(perMinute),
      perTextConv: atMargin(perTextConv),
      perChatConv: atMargin(perChatConv),
    },
    stackLabel: stack.label,
  };
}

// --- the two assumptions this browser remembers ----------------------------

/**
 * Where the margin and the client count are kept between visits.
 *
 * `localStorage`, which means per browser and per admin — not a setting the
 * agency shares. Somewhere shared would be a column on the portal's own
 * database and a Prisma migration with it; these two numbers are a convenience
 * for whoever is quoting, and the quote prints them beside its answer so a
 * remembered value is never a hidden one.
 */
export const ASSUMPTIONS_STORAGE_KEY = "spatalk.admin.pricing.assumptions";

export type StoredAssumptions = { margin: number; clients: number };

/** As much of `Storage` as this module uses, so a test can hand it a fake. */
export type StorageLike = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
};

export const DEFAULT_ASSUMPTIONS: StoredAssumptions = {
  margin: DEFAULT_MARGIN,
  clients: DEFAULT_CLIENTS,
};

/** A whole number of clients, at least one. */
export function clampClients(clients: number): number {
  if (!Number.isFinite(clients)) {
    return DEFAULT_CLIENTS;
  }
  return Math.max(1, Math.floor(clients));
}

/**
 * What this browser remembers, or the defaults. Every failure — no storage, a
 * browser that refuses it, a key holding something else entirely — is the
 * defaults, because a quote built on a value nobody can read is worse than one
 * built on the number the page says it is using.
 */
export function loadAssumptions(
  storage: StorageLike | null | undefined,
): StoredAssumptions {
  if (!storage) {
    return { ...DEFAULT_ASSUMPTIONS };
  }

  let raw: string | null = null;
  try {
    raw = storage.getItem(ASSUMPTIONS_STORAGE_KEY);
  } catch {
    return { ...DEFAULT_ASSUMPTIONS };
  }
  if (raw === null) {
    return { ...DEFAULT_ASSUMPTIONS };
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) {
      return { ...DEFAULT_ASSUMPTIONS };
    }
    const { margin, clients } = parsed as Partial<StoredAssumptions>;
    if (
      typeof margin !== "number" ||
      !Number.isFinite(margin) ||
      margin < 0 ||
      margin >= 1 ||
      typeof clients !== "number" ||
      !Number.isFinite(clients) ||
      clients < 1
    ) {
      return { ...DEFAULT_ASSUMPTIONS };
    }
    return { margin, clients: Math.floor(clients) };
  } catch {
    return { ...DEFAULT_ASSUMPTIONS };
  }
}

export function saveAssumptions(
  assumptions: StoredAssumptions,
  storage: StorageLike | null | undefined,
): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(
      ASSUMPTIONS_STORAGE_KEY,
      JSON.stringify({
        margin: clampMargin(assumptions.margin),
        clients: clampClients(assumptions.clients),
      }),
    );
  } catch {
    // A browser with storage turned off still gets a working page; it just
    // starts from the defaults every time.
  }
}
