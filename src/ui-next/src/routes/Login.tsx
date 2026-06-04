// Login.tsx — minimal but real sign-in landing (Task 2.4 placeholder).
//
// The full two-column landing (BACKED-BY chips, value-props, OVERVIEW teaser)
// arrives in Task 2.5; for now this is a clean centered card with the brand
// lockup and a SINGLE primary CTA that links to /api/oauth/login?action=ui — the
// ONLY OIDC redirect trigger (T-09-17 open-redirect: a FIXED string literal,
// never built from a prop/query/next/hash).
//
// The ?action=ui param makes the callback eager-create the LiteLLM user WITHOUT
// minting a key (D-13), matching the old TwoColumnLogin SSO entrypoint.

import type { AppConfig } from '@/lib/api-types';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { BrandLockup } from '@/components/layout/BrandLockup';

// The SOLE redirect trigger. FIXED literal — do NOT construct from any prop.
const SSO_LOGIN_URL = '/api/oauth/login?action=ui';

export interface LoginProps {
  config: AppConfig;
}

export function Login({ config }: LoginProps) {
  return (
    <div className="flex min-h-screen flex-1 items-center justify-center bg-background p-8">
      <Card className="w-full max-w-[440px] gap-0 py-0">
        <div className="border-b border-border px-8 pt-8 pb-6">
          <BrandLockup
            config={config}
            className="text-2xl tracking-tight"
            iconClassName="size-[26px]"
          />
          <h1 className="mt-5 text-2xl font-semibold leading-tight text-text-primary">
            Sign in
          </h1>
          {config.tagline ? (
            <p className="mt-1.5 text-sm text-text-secondary">{config.tagline}</p>
          ) : (
            <p className="mt-1.5 text-sm text-text-secondary">
              Authenticate to provision your LiteLLM key.
            </p>
          )}
        </div>
        <div className="px-8 py-7">
          <Button
            asChild
            className="w-full font-mono lowercase tracking-wide"
          >
            <a href={SSO_LOGIN_URL}>Sign in</a>
          </Button>
        </div>
      </Card>
    </div>
  );
}
