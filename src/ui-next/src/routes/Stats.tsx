// Stats.tsx — the #/stats authenticated content slot (Task 2.4 STUB).
//
// The real usage/spend dashboard (KPIs, charts, per-model + top-keys tables)
// arrives in Phase 4. On this route the AppShell HIDES its right sidebar
// (parity with app.js `route !== "stats"`), so this stub renders full width.

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function Stats() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Usage &amp; Spend</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-text-secondary">
          Usage &amp; Spend — coming in Phase 4
        </p>
      </CardContent>
    </Card>
  );
}
