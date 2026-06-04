import '@testing-library/jest-dom';

// --- jsdom + Node-fetch AbortSignal reconciliation -------------------------
// react-router v7's data router (createHashRouter) drives client-side
// navigation by constructing `new Request(url, { signal })`, where `signal`
// comes from a `globalThis.AbortController`. Under the vitest jsdom env the
// global `Request` is Node's (undici-backed) implementation while
// `AbortController`/`AbortSignal` are jsdom's. undici's `Request` constructor
// brand-checks the signal and rejects jsdom's instance with
// "RequestInit: Expected signal to be an instance of AbortSignal", surfacing as
// an unhandled rejection during the `*` -> Navigate("/") redirect.
//
// We can't reconcile the two realms (a native AbortSignal from any other realm
// also fails undici's identity check) and undici isn't an installable package
// here, so we wrap the global `Request` with a subclass that drops a
// cross-realm `signal` from the init. The router does not rely on aborting
// these navigations in tests, so stripping the signal is safe and keeps
// navigations (and the redirect assertion) settling cleanly.
const BaseRequest = globalThis.Request;

class PatchedRequest extends BaseRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init && 'signal' in init) {
      const { signal: _signal, ...rest } = init;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
}

globalThis.Request = PatchedRequest as unknown as typeof globalThis.Request;
