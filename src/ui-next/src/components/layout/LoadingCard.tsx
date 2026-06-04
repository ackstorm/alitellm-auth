// LoadingCard.tsx — the loading-state shell card (ported from src/ui/app.js
// LoadingCard). Rendered for BOTH the `loading` and `expired` views (expired
// also fires a silent redirect effect in App.tsx, so the card is only a brief
// placeholder). All copy is LOCKED per the UI-SPEC §Copywriting Contract:
// INITIALIZING / "Connecting to alitellm-auth..." / "Verifying your session,
// please wait." / "checking session".
//
// The card takes `config` so the surrounding driver can stay config-aware, but
// the locked copy strings are intentionally NOT derived from config (parity with
// app.js, where LoadingCard takes no props and hardcodes the literals).

import type { AppConfig } from '@/lib/api-types';
import { Card } from '@/components/ui/card';

export interface LoadingCardProps {
  config: AppConfig;
}

export function LoadingCard({ config: _config }: LoadingCardProps) {
  return (
    <div
      data-state="loading"
      className="flex flex-1 items-center justify-center p-8 min-h-screen"
    >
      <Card className="w-full max-w-[620px] gap-0 py-0">
        <div className="border-b border-border px-8 pt-8 pb-6">
          <div className="mb-4 flex items-center gap-2.5">
            <span className="size-2 animate-pulse rounded-full bg-primary shadow-[0_0_8px_var(--primary)]" />
            <span className="font-mono text-xs font-semibold tracking-widest text-primary">
              INITIALIZING
            </span>
          </div>
          <h1 className="text-2xl font-semibold leading-tight text-text-primary">
            Connecting to alitellm-auth...
          </h1>
          <p className="mt-1.5 text-sm text-text-secondary">
            Verifying your session, please wait.
          </p>
        </div>
        <div className="px-8 py-7">
          <span className="font-mono text-xs tracking-wider text-text-secondary">
            checking session...
          </span>
        </div>
      </Card>
    </div>
  );
}
