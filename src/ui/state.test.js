// state.test.js — vitest unit suite for the pure resolveState() state machine
// and the apiFetch network-failure mapping. Runs in the default node
// environment (no jsdom) because resolveState is pure (no DOM/network refs).
import { describe, it, expect, vi, afterEach } from "vitest";
import { resolveState } from "./state.js";
import { apiFetch } from "./api.js";

describe("resolveState — five shell states", () => {
  it("null status before the first response resolves -> loading", () => {
    expect(resolveState(null, false)).toBe("loading");
    expect(resolveState(undefined, false)).toBe("loading");
  });

  it("200 -> authed", () => {
    expect(resolveState(200, false)).toBe("authed");
    expect(resolveState(200, true)).toBe("authed");
  });

  it("401 on a cold load (hasLoaded false) -> signin (NOT redirect)", () => {
    expect(resolveState(401, false)).toBe("signin");
  });

  it("401 after a successful load (hasLoaded true) -> expired (silent redirect)", () => {
    expect(resolveState(401, true)).toBe("expired");
  });

  it("non-401 errors and network failure -> error", () => {
    expect(resolveState(502, false)).toBe("error");
    expect(resolveState(503, true)).toBe("error");
    expect(resolveState(0, false)).toBe("error"); // network/fetch failure
    expect(resolveState(500, false)).toBe("error");
    expect(resolveState(404, true)).toBe("error");
  });

  it("is pure — same inputs always yield the same output", () => {
    expect(resolveState(401, false)).toBe(resolveState(401, false));
    expect(resolveState(401, true)).toBe(resolveState(401, true));
  });
});

describe("apiFetch — { status, data } + network-failure mapping", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns { status, data } on a JSON response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 200,
        json: async () => ({ email: "alice@example.com" }),
      })),
    );
    const result = await apiFetch("/api/session/me");
    expect(result.status).toBe(200);
    expect(result.data).toEqual({ email: "alice@example.com" });
  });

  it("maps a thrown network error to status 0 (no uncaught rejection)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const result = await apiFetch("/api/session/me");
    expect(result.status).toBe(0);
    expect(result.data).toBeNull();
  });

  it("tolerates a non-JSON / empty body (e.g. a bare 401)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 401,
        json: async () => {
          throw new SyntaxError("Unexpected end of JSON input");
        },
      })),
    );
    const result = await apiFetch("/api/session/me");
    expect(result.status).toBe(401);
    expect(result.data).toBeNull();
  });
});
