// HowTo.tsx — the "How-to" guide route (nav: KEYS | STATS | HOWTO).
//
// Placeholder for now: real step-by-step content (create a key, call the
// gateway, set a budget) is a follow-up. This stub keeps the nav link live (no
// dead route) and matches the dark card style of the other routes. Rendered
// inside AppShell via <Outlet/>, so it inherits the topbar + footer chrome.

export function HowTo() {
  return (
    <section className="mx-auto max-w-2xl py-16 text-center">
      <h1 className="text-2xl font-semibold leading-tight text-text-primary">
        How-to
      </h1>
      <p className="mt-4 text-sm text-text-secondary">
        Step-by-step guides — creating a virtual key, calling the gateway with
        it, and tracking spend — are coming soon.
      </p>
    </section>
  );
}
