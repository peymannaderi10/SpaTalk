import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

/**
 * The one module that holds the shared key and names the person acting.
 *
 * Three promises are proved here without a runtime, a network or a key: the key
 * is read from the environment once and never travels any further, every call
 * carries the acting person so the runtime can write the audit row, and a
 * failure reaches a page as a sentence — never a stack, never a status line,
 * and never the key, in the thrown error or in the log.
 */

const RUNTIME_URL = "http://runtime.test:8000";
const RUNTIME_KEY = "internal-key-0123456789abcdef";

const counters = vi.hoisted(() => ({ keyReads: 0, urlReads: 0 }));

vi.mock("wasp/server", () => {
  class HttpError extends Error {
    public statusCode: number;
    public data: unknown;

    constructor(statusCode: number, message?: string, data?: unknown) {
      super(message);
      this.statusCode = statusCode;
      this.data = data;
    }
  }

  const env = {
    get RUNTIME_INTERNAL_KEY() {
      counters.keyReads += 1;
      return "internal-key-0123456789abcdef";
    },
    get RUNTIME_INTERNAL_URL() {
      counters.urlReads += 1;
      return "http://runtime.test:8000";
    },
  };

  return { HttpError, env };
});

import { runtime, runtimeCall, __resetRuntimeCredentials } from "./api";

type Call = { request: Request };
const calls: Call[] = [];

function answerWith(
  status: number,
  body: unknown = {},
): (input: Request) => Promise<Response> {
  return async (input: Request) => {
    calls.push({ request: input });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
}

beforeEach(() => {
  calls.length = 0;
  counters.keyReads = 0;
  counters.urlReads = 0;
  __resetRuntimeCredentials();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the shared key", () => {
  test("is read from the environment once, however many calls are made", async () => {
    vi.stubGlobal("fetch", vi.fn(answerWith(200, [])));

    for (let i = 0; i < 5; i += 1) {
      const api = runtime("dana@clinic.test");
      await api.GET("/internal/tenants");
    }

    expect(counters.keyReads).toBe(1);
    expect(counters.urlReads).toBe(1);
  });

  test("is presented to the runtime and to nobody else", async () => {
    vi.stubGlobal("fetch", vi.fn(answerWith(200, [])));

    const api = runtime("dana@clinic.test");
    await api.GET("/internal/tenants");

    const sent = calls[0].request;
    expect(sent.url.startsWith(RUNTIME_URL)).toBe(true);
    expect(sent.headers.get("X-Internal-Key")).toBe(RUNTIME_KEY);
  });
});

describe("naming the person who is acting", () => {
  test("every call carries the acting person in X-Actor", async () => {
    vi.stubGlobal("fetch", vi.fn(answerWith(200, [])));

    const api = runtime("dana@clinic.test");
    await api.GET("/internal/tenants");

    expect(calls[0].request.headers.get("X-Actor")).toBe("dana@clinic.test");
  });

  test("a call that cannot name anybody is refused before it is made", async () => {
    const fetchSpy = vi.fn(answerWith(200, []));
    vi.stubGlobal("fetch", fetchSpy);

    expect(() => runtime("")).toThrowError();
    expect(() => runtime("   ")).toThrowError();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("the refusal to act anonymously does not mention the key", () => {
    let message = "";
    try {
      runtime("");
    } catch (caught) {
      message = caught instanceof Error ? `${caught.message}${caught.stack}` : "";
    }

    expect(message).not.toContain(RUNTIME_KEY);
  });
});

describe("a failing runtime call", () => {
  test("reaches the page as a sentence, with no stack and no status line", async () => {
    vi.stubGlobal("fetch", vi.fn(answerWith(500, { detail: "Traceback…" })));
    const api = runtime("dana@clinic.test");

    let thrown: unknown;
    try {
      await runtimeCall(
        () => api.GET("/internal/tenants"),
        "the list of clinics",
      );
    } catch (caught) {
      thrown = caught;
    }

    const error = thrown as { statusCode: number; message: string };
    expect(error.statusCode).toBe(502);
    expect(error.message).toContain("the list of clinics");
    expect(error.message).not.toContain("500");
    expect(error.message).not.toContain("Traceback");
    expect(error.message).not.toMatch(/\bat\s+\S+\s+\(/);
  });

  test("never carries the key, in the message or anywhere on the error", async () => {
    vi.stubGlobal("fetch", vi.fn(answerWith(401, { detail: "invalid key" })));
    const api = runtime("dana@clinic.test");

    let thrown: unknown;
    try {
      await runtimeCall(() => api.GET("/internal/tenants"), "the clinics");
    } catch (caught) {
      thrown = caught;
    }

    const error = thrown as Error & { data?: unknown };
    const everything = [
      error.message,
      error.stack ?? "",
      JSON.stringify(error.data ?? null),
    ].join(" ");
    expect(everything).not.toContain(RUNTIME_KEY);
  });

  test("is logged without the key", async () => {
    const logged: string[] = [];
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      logged.push(args.map((arg) => String(arg)).join(" "));
    });
    vi.stubGlobal("fetch", vi.fn(answerWith(500, { detail: "boom" })));
    const api = runtime("dana@clinic.test");

    await expect(
      runtimeCall(() => api.GET("/internal/tenants"), "the clinics"),
    ).rejects.toBeTruthy();

    expect(logged.join("\n")).not.toContain(RUNTIME_KEY);
  });

  test("a connection that was never made is still a sentence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error(`connect ECONNREFUSED ${RUNTIME_URL}`);
      }),
    );
    const api = runtime("dana@clinic.test");

    let thrown: unknown;
    try {
      await runtimeCall(() => api.GET("/internal/tenants"), "the clinics");
    } catch (caught) {
      thrown = caught;
    }

    const error = thrown as { statusCode: number; message: string };
    expect(error.statusCode).toBe(502);
    expect(error.message).not.toContain("ECONNREFUSED");
  });

  test("a refused configuration still names the fields that were wrong", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        answerWith(422, {
          detail: [{ loc: ["config", "hours"], msg: "end before start" }],
        }),
      ),
    );
    const api = runtime("dana@clinic.test");

    let thrown: unknown;
    try {
      await runtimeCall(
        () =>
          api.PUT("/internal/tenants/{tenant_id}/config", {
            params: { path: { tenant_id: "skincentrix" } },
            body: { config: {}, created_by: "dana@clinic.test" },
          }),
        "the settings",
      );
    } catch (caught) {
      thrown = caught;
    }

    const error = thrown as { statusCode: number; data: { fieldErrors: Array<{ field: string }> } };
    expect(error.statusCode).toBe(422);
    expect(error.data.fieldErrors[0].field).toBe("hours");
  });
});
