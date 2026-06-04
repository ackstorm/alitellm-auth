// Dashboard.tsx — the #/ authenticated content slot (Task 2.4 STUB).
//
// Shows the resolved identity (email / team / endpoint) from the session `me`.
// The real keys table + create/delete modals arrive in Phase 3 — this stub just
// proves the authed shell mounts the route and threads `me` correctly.

import type { SessionMe } from '@/lib/api-types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface DashboardProps {
  me: SessionMe;
}

export function Dashboard({ me }: DashboardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Dashboard</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 font-mono text-xs">
          <dt className="text-text-secondary">email</dt>
          <dd className="text-text-primary">{me.email}</dd>
          <dt className="text-text-secondary">team_id</dt>
          <dd className="text-text-primary">{me.team_id}</dd>
          <dt className="text-text-secondary">endpoint</dt>
          <dd className="text-text-primary">{me.endpoint}</dd>
        </dl>
        <p className="mt-6 text-sm text-text-secondary">Keys — coming in Phase 3</p>
      </CardContent>
    </Card>
  );
}
