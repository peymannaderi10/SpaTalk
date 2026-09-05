import { existsSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { describe, expect, it } from "vitest";
import {
  ASSUMPTIONS_STORAGE_KEY,
  DEFAULT_CLIENTS,
  DEFAULT_MARGIN,
  clampMargin,
  conversationAssumptions,
  defaultInputs,
  fixedPlatformCad,
  loadAssumptions,
  marginOf,
  measured,
  outboundMessage,
  priceAtMargin,
  quote,
  recommendedTextStack,
  recommendedVoiceStack,
  saveAssumptions,
  textConversation,
  voicePerMinute,
  type RatesFile,
} from "./pricing";

/**
 * The port of `docs/research/costmodel.py`, pinned against the Python itself.
 *
 * Every figure below was printed by running the model once —
 * `cd runtime && .venv/Scripts/python.exe ../docs/research/costmodel.py
 * ../docs/research/rates.json` — and is asserted to four decimal places, which
 * is the precision the Python prints. The rates file is loaded from disk rather
 * than copied here, so a rate that changes changes the Python and this test
 * together; a port that drifts from the model is what these numbers catch.
 *
 * Nothing here reaches the network. The runtime serves the same file at
 * `GET /internal/rates`, and `runtime/spatalk/rates.json` is pinned equal to it
 * by a runtime test, so the file on disk is the file the page will be quoting
 * against.
 */

function findPortalRoot(): string {
  let dir = process.cwd();
  for (let hop = 0; hop < 8; hop += 1) {
    if (existsSync(join(dir, "main.wasp.ts"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`could not find the portal root above ${process.cwd()}`);
}

const RATES: RatesFile = JSON.parse(
  readFileSync(
    join(findPortalRoot(), "..", "docs", "research", "rates.json"),
    "utf8",
  ),
) as RatesFile;

/** The Python prints its CAD figures with `:.4f`; this is the same rounding. */
function cad4(value: number): number {
  return Number(value.toFixed(4));
}

function voiceStackCad(name: string): number {
  const stack = RATES.voice_stacks[name];
  expect(stack, `no voice stack called ${name}`).toBeDefined();
  const perMinute = voicePerMinute(
    RATES.telephony[stack.tel],
    RATES.stt[stack.stt],
    RATES.tts[stack.tts],
    RATES.llm[stack.llm],
    RATES.assumptions,
  );
  return cad4(perMinute.totalUsd * RATES.usd_to_cad);
}

describe("the cost model, against the Python it is a port of", () => {
  it("reproduces the per-call-minute figure for every voice stack in the file", () => {
    // `=== VOICE, per call-minute (all-in) ===`
    expect(
      voiceStackCad(
        "A  founder suggestion at today's real prices (Telnyx + Flux + Aura-2 + Gemini Flash)",
      ),
    ).toBe(0.048);
    expect(
      voiceStackCad(
        "B  RECOMMENDED (Telnyx + Soniox + Inworld Flash + Gemini 2.5 Flash)",
      ),
    ).toBe(0.0314);
    expect(
      voiceStackCad("B2 same but Deepgram Flux for native end-of-turn"),
    ).toBe(0.0394);
    expect(voiceStackCad("B3 same but Flash-Lite LLM")).toBe(0.03);
    expect(
      voiceStackCad("C  cheapest (Plivo + Soniox + Inworld + Flash-Lite)"),
    ).toBe(0.0224);
    expect(
      voiceStackCad(
        "D  expensive reference (Twilio + Nova-3 + ElevenLabs + Haiku 4.5)",
      ),
    ).toBe(0.0631);
    expect(voiceStackCad("B4 Soniox only (STT + TTS), single vendor")).toBe(
      0.0309,
    );
  });

  it("splits a call-minute the way the Python's breakdown line does", () => {
    // `breakdown USD/min: tel 0.0130  stt 0.0020  tts 0.0062  llm 0.0014`
    const stack =
      RATES.voice_stacks[
        "B  RECOMMENDED (Telnyx + Soniox + Inworld Flash + Gemini 2.5 Flash)"
      ];
    const perMinute = voicePerMinute(
      RATES.telephony[stack.tel],
      RATES.stt[stack.stt],
      RATES.tts[stack.tts],
      RATES.llm[stack.llm],
      RATES.assumptions,
    );
    expect(cad4(perMinute.tel)).toBe(0.013);
    expect(cad4(perMinute.stt)).toBe(0.002);
    expect(cad4(perMinute.tts)).toBe(0.0062);
    expect(cad4(perMinute.llm)).toBe(0.0014);
    expect(cad4(perMinute.totalUsd)).toBe(
      cad4(perMinute.tel + perMinute.stt + perMinute.tts + perMinute.llm),
    );
  });

  it("reproduces both text stacks: an SMS conversation, a chat conversation and one outbound message", () => {
    // `=== TEXT conversation (SMS incl. carrier fees; chat has no msg cost) ===`
    const assumptions = conversationAssumptions(RATES);
    const expected: Record<string, [number, number, number]> = {
      "Telnyx CA toll-free + Gemini 2.5 Flash": [0.1423, 0.0033, 0.0174],
      "Twilio CA toll-free + Gemini 2.5 Flash": [0.2234, 0.0033, 0.0227],
    };

    for (const [name, [sms, chat, outbound]] of Object.entries(expected)) {
      const stack = RATES.text_stacks[name];
      expect(stack, `no text stack called ${name}`).toBeDefined();
      const messaging = RATES.sms[stack.sms];
      const model = RATES.llm[stack.llm];
      const fx = RATES.usd_to_cad;

      expect(
        cad4(
          textConversation(messaging, model, "sms", assumptions).totalUsd * fx,
        ),
        `${name}: SMS conversation`,
      ).toBe(sms);
      expect(
        cad4(
          textConversation(messaging, model, "chat", assumptions).totalUsd * fx,
        ),
        `${name}: web-chat conversation`,
      ).toBe(chat);
      expect(
        cad4(outboundMessage(messaging).totalUsd * fx),
        `${name}: single outbound SMS`,
      ).toBe(outbound);
    }
  });

  it("charges a web chat for the model and nothing else", () => {
    const assumptions = conversationAssumptions(RATES);
    const messaging = RATES.sms["telnyx_ca_tollfree"];
    const model = RATES.llm["gemini_25_flash"];
    const chat = textConversation(messaging, model, "chat", assumptions);
    expect(chat.msgs).toBe(0);
    expect(chat.totalUsd).toBe(chat.llm);
  });

  it("picks the fixed-cost tier the Python picks", () => {
    // `=== FIXED platform cost, CAD/month ===`
    expect(cad4(fixedPlatformCad(RATES.fixed_cad, 1))).toBe(24.51);
    // Five clients are on the one-client bill of materials: the tiers are
    // "1", "10" and "25", and the highest tier at or below the count wins.
    expect(cad4(fixedPlatformCad(RATES.fixed_cad, 5))).toBe(24.51);
    expect(cad4(fixedPlatformCad(RATES.fixed_cad, 10))).toBe(72.09);
    expect(cad4(fixedPlatformCad(RATES.fixed_cad, 25))).toBe(216.45);
    // Above the last tier the last tier is still the answer.
    expect(cad4(fixedPlatformCad(RATES.fixed_cad, 40))).toBe(216.45);
  });

  it("names the stacks the file marks recommended", () => {
    expect(recommendedVoiceStack(RATES)).toBe(
      "B  RECOMMENDED (Telnyx + Soniox + Inworld Flash + Gemini 2.5 Flash)",
    );
    expect(recommendedTextStack(RATES)).toBe(
      "Telnyx CA toll-free + Gemini 2.5 Flash",
    );
  });
});

describe("margin arithmetic", () => {
  it("treats margin as margin, not markup", () => {
    // 65% margin means the cost is 35% of the price: 100 / 0.35.
    expect(priceAtMargin(100, 0.65)).toBeCloseTo(285.7142857, 4);
    expect(priceAtMargin(100, 0)).toBe(100);
    expect(priceAtMargin(0, 0.65)).toBe(0);
  });

  it("reads a margin back off a price", () => {
    expect(marginOf(100, 285.7142857142857)).toBeCloseTo(0.65, 10);
    expect(marginOf(100, 200)).toBeCloseTo(0.5, 10);
    // Nothing is being sold, so there is no margin to report.
    expect(marginOf(100, 0)).toBeNull();
  });

  it("keeps a margin under one, because a cost is never nothing", () => {
    expect(clampMargin(0.65)).toBe(0.65);
    expect(clampMargin(1)).toBeLessThan(1);
    expect(clampMargin(4)).toBeLessThan(1);
    expect(clampMargin(-2)).toBe(0);
    expect(clampMargin(Number.NaN)).toBe(DEFAULT_MARGIN);
  });
});

describe("the quote at the founder's defaults", () => {
  const inputs = defaultInputs(RATES);

  it("starts from the volumes and the stacks the rates file states", () => {
    expect(inputs).toEqual({
      clients: 1,
      margin: 0.65,
      callsPerMonth: 250,
      avgCallMinutes: 3,
      smsConvsPerMonth: 150,
      chatConvsPerMonth: 100,
      outboundMsgsPerMonth: 300,
      voiceStack: recommendedVoiceStack(RATES),
      textStack: recommendedTextStack(RATES),
    });
    expect(inputs.margin).toBe(DEFAULT_MARGIN);
    expect(inputs.clients).toBe(DEFAULT_CLIENTS);
  });

  it("reproduces the Python's cost per tenant and its margin at the list price", () => {
    const result = quote(inputs, RATES);

    // `variable+per-tenant cost per tenant: 54.97 CAD/month` plus the
    // `1 tenants: cost 79.48` line of the margin table.
    expect(cad4(result.cogsCad)).toBe(79.4811);
    expect(cad4(result.priceCad)).toBe(227.089);
    // `1 tenants: ... gross margin 92.0%`
    expect(marginOf(result.cogsCad, 999)).toBeCloseTo(0.9204392988, 6);
  });

  it("breaks the month down into the six lines the page prints", () => {
    const result = quote(inputs, RATES);
    const lines = Object.fromEntries(
      result.breakdown.map((line) => [line.id, cad4(line.cad)]),
    );

    expect(lines).toEqual({
      voice: 23.5824,
      sms: 21.3443,
      chat: 0.3335,
      outbound: 5.211,
      "per-tenant-fixed": 4.5,
      "platform-share": 24.51,
    });
    expect(
      cad4(result.breakdown.reduce((sum, line) => sum + line.cad, 0)),
    ).toBe(cad4(result.cogsCad));
  });

  it("gives the unit costs the model implies", () => {
    const result = quote(inputs, RATES);
    expect(cad4(result.perMinute)).toBe(0.0314);
    expect(cad4(result.perCall)).toBe(0.0943);
    expect(cad4(result.perTextConv)).toBe(0.1423);
    expect(cad4(result.perChatConv)).toBe(0.0033);
  });

  it("shares the platform's fixed cost between the clients on it", () => {
    const alone = quote(inputs, RATES);
    const ten = quote({ ...inputs, clients: 10 }, RATES);

    const shareOf = (result: ReturnType<typeof quote>) =>
      result.breakdown.find((line) => line.id === "platform-share")?.cad ?? 0;

    expect(cad4(shareOf(alone))).toBe(24.51);
    expect(cad4(shareOf(ten))).toBe(cad4(72.09 / 10));
    expect(ten.cogsCad).toBeLessThan(alone.cogsCad);
  });

  it("moves the price with the margin and nothing else", () => {
    const at65 = quote(inputs, RATES);
    const at80 = quote({ ...inputs, margin: 0.8 }, RATES);

    expect(at80.cogsCad).toBe(at65.cogsCad);
    expect(cad4(at80.priceCad)).toBe(cad4(at65.cogsCad / 0.2));
  });

  it("refuses a stack the rates file does not have", () => {
    expect(() => quote({ ...inputs, voiceStack: "nope" }, RATES)).toThrow(
      /voice stack/i,
    );
    expect(() => quote({ ...inputs, textStack: "nope" }, RATES)).toThrow(
      /text stack/i,
    );
  });
});

describe("what a tenant actually cost", () => {
  it("divides the runtime's own figures and nothing more", () => {
    const row = measured({ calls: 20, callMinutes: 50, estCostCad: 12.5 });
    expect(row.perCall).toBeCloseTo(0.625, 10);
    expect(row.perMinute).toBeCloseTo(0.25, 10);
  });

  it("says nothing rather than dividing by no calls", () => {
    const row = measured({ calls: 0, callMinutes: 0, estCostCad: 0 });
    expect(row.perCall).toBeNull();
    expect(row.perMinute).toBeNull();
  });
});

describe("the assumptions this browser remembers", () => {
  function fakeStorage(seed: Record<string, string> = {}) {
    const store = new Map(Object.entries(seed));
    return {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      read: () => Object.fromEntries(store),
    };
  }

  it("falls back to 65% and one client when nothing is stored", () => {
    expect(loadAssumptions(fakeStorage())).toEqual({
      margin: DEFAULT_MARGIN,
      clients: DEFAULT_CLIENTS,
    });
  });

  it("survives a reload: what was saved is what comes back", () => {
    const storage = fakeStorage();
    saveAssumptions({ margin: 0.72, clients: 8 }, storage);

    // A fresh reader of the same storage — which is what a reload is.
    expect(loadAssumptions(fakeStorage(storage.read()))).toEqual({
      margin: 0.72,
      clients: 8,
    });
    expect(Object.keys(storage.read())).toEqual([ASSUMPTIONS_STORAGE_KEY]);
  });

  it("hands the remembered pair back to the form the page starts from", () => {
    // What a reload actually does: read the storage, build the inputs. The
    // client's volumes come from the rates file every time; only these two
    // are the admin's own and remembered.
    const storage = fakeStorage();
    saveAssumptions({ margin: 0.5, clients: 12 }, storage);

    const reloaded = defaultInputs(
      RATES,
      loadAssumptions(fakeStorage(storage.read())),
    );
    expect(reloaded.margin).toBe(0.5);
    expect(reloaded.clients).toBe(12);
    expect(reloaded.callsPerMonth).toBe(RATES.assumptions_volume.calls_per_month);
    expect(quote(reloaded, RATES).priceCad).toBeCloseTo(
      quote(reloaded, RATES).cogsCad / 0.5,
      10,
    );
  });

  it("ignores anything stored that is not a margin and a client count", () => {
    expect(
      loadAssumptions(fakeStorage({ [ASSUMPTIONS_STORAGE_KEY]: "{oh no" })),
    ).toEqual({ margin: DEFAULT_MARGIN, clients: DEFAULT_CLIENTS });
    expect(
      loadAssumptions(
        fakeStorage({
          [ASSUMPTIONS_STORAGE_KEY]: JSON.stringify({
            margin: "most of it",
            clients: 0,
          }),
        }),
      ),
    ).toEqual({ margin: DEFAULT_MARGIN, clients: DEFAULT_CLIENTS });
  });

  it("does not fall over when the browser refuses storage", () => {
    const refuses = {
      getItem: () => {
        throw new Error("storage is off");
      },
      setItem: () => {
        throw new Error("storage is off");
      },
    };
    expect(loadAssumptions(refuses)).toEqual({
      margin: DEFAULT_MARGIN,
      clients: DEFAULT_CLIENTS,
    });
    expect(() => saveAssumptions({ margin: 0.5, clients: 2 }, refuses)).not.toThrow();
    expect(loadAssumptions(null)).toEqual({
      margin: DEFAULT_MARGIN,
      clients: DEFAULT_CLIENTS,
    });
  });
});
