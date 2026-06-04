// KeysTable.tsx — the keys-as-DATA-TABLE surface for the alitellm-auth console
// (DASH-02 / DASH-03 / DASH-06). React + Tailwind, rendered through the generic
// DataTable<T>. Parity reference: src/ui/keys-table.js.
//
// Unlike the old presentational leaf, this component OWNS its data: it calls
// useKeys() internally and reads the in-memory fresh-keys store. The actual
// DELETE + confirm modal is wired by the parent later (Task 3.7); KeysTable only
// invokes onDelete(row) from the per-row revoke action.
//
// SCOPE NOTE: the old table's chevron-expandable per-key usage-detail row
// (Spend/TPM/RPM/Budget) and the client-side "Showing X of Y" pagination are
// intentionally OUT OF SCOPE here (tracked as a known parity gap) — the generic
// DataTable is single-row-per-item and 3.4's scope is columns/labels/empty/
// copy/delete.
//
// SECURITY INVARIANTS (threat register 10-03 / 14-03):
//   • T-10-07 (info disclosure, fresh keys): the full sk- lives ONLY in the
//     in-memory freshKeys store. It is shown only on an explicit reveal/copy
//     click, is NEVER logged, and never appears in a title/aria-label/error.
//   • T-10-08 (info disclosure, pre-existing keys): pre-existing keys have NO
//     full value client-side — copy emits only the public key id, and no reveal
//     button is rendered.

import * as React from 'react';
import { Check, Copy, Eye, EyeOff, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import { useCopyFeedback } from '@/hooks/use-copy-feedback';
import { useKeys } from '@/hooks/use-keys';
import { formatDate, maskKey } from '@/lib/format';
import { isExpired, isRevoked, selectKeyRows } from '@/lib/keys';
import type { KeyRow } from '@/lib/api-types';
import { cn } from '@/lib/utils';
import { useFreshKeysStore } from '@/stores/fresh-keys';

// The em-dash placeholder (matches format.ts EM_DASH) for the always-empty
// "Last used" cell (the backend emits no last-used — parity with the old table).
const EM_DASH = '—';

// The masked fresh-key default — a fixed-width run of bullets shown until the
// user explicitly toggles reveal. NOT derived from the secret (no length leak).
const MASKED_FRESH = 'sk-••••••••••••••••••••';

type KeysTableProps = {
  /** Invoked by the per-row revoke action. The parent owns the confirm + DELETE. */
  onDelete: (row: KeyRow) => void;
};

/** Status precedence: Revoked > Expired > Active (UI-SPEC §C4). */
function statusFor(row: KeyRow): {
  label: 'Revoked' | 'Expired' | 'Active';
  variant: 'default' | 'outline' | 'destructive';
} {
  if (isRevoked(row)) return { label: 'Revoked', variant: 'destructive' };
  if (isExpired(row)) return { label: 'Expired', variant: 'outline' };
  return { label: 'Active', variant: 'default' };
}

// CopyButton — encapsulates one row's copy-feedback so each row's "copied" state
// is independent. Copies `value` (full sk- for a fresh key, else the public id).
function CopyButton({ value }: { value: string }): React.ReactElement {
  const { copied, copy } = useCopyFeedback();
  const Icon = copied ? Check : Copy;
  return (
    <button
      type="button"
      data-slot="key-copy"
      aria-label={copied ? 'Copied' : 'Copy'}
      title={copied ? 'Copied' : 'Copy'}
      onClick={() => void copy(value)}
      className={cn(
        'inline-flex size-7 items-center justify-center rounded-md border transition-colors',
        copied
          ? 'border-primary text-primary'
          : 'text-muted-foreground hover:text-foreground border-border'
      )}
    >
      <Icon className="size-[15px]" aria-hidden="true" />
    </button>
  );
}

export function KeysTable({ onDelete }: KeysTableProps): React.ReactElement {
  const query = useKeys();
  const rows = selectKeyRows(query.data);
  const freshKeys = useFreshKeysStore((s) => s.freshKeys);

  // Reveal state is shared between the Key ID chip and the reveal action, so it
  // lives here. toggleReveal returns a NEW Set so React sees the change.
  const [revealedIds, setRevealedIds] = React.useState<Set<string>>(
    () => new Set()
  );
  const toggleReveal = React.useCallback((id: string) => {
    setRevealedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ── State branches (exact copy lifted from keys-table.js) ───────────────────
  if (query.isPending) {
    return (
      <div
        data-slot="keys-table-state"
        className="bg-card text-card-foreground rounded-xl border px-4 py-12 text-center"
      >
        <p className="text-muted-foreground text-sm">Loading your keys…</p>
      </div>
    );
  }

  if (query.isError) {
    return (
      <div
        data-slot="keys-table-state"
        className="bg-card text-card-foreground rounded-xl border px-4 py-12 text-center"
      >
        <p className="text-destructive text-sm">
          Couldn&apos;t load your keys. Refresh the page to try again.
        </p>
      </div>
    );
  }

  const columns: DataTableColumn<KeyRow>[] = [
    {
      key: 'keyid',
      header: 'Key ID',
      headerClassName: 'whitespace-nowrap',
      // align-top (the cell is a two-line stack). The pre-existing key id is
      // shown MASKED to a short prefix…last4 (maskKey) — the full 64-char hash
      // would force the table wider than the ~800px main column and scroll
      // Status + the row actions off the right edge under overflow-x-auto. The
      // FULL public id stays available via the Copy action.
      className: 'align-top',
      cell: (row) => {
        const id = row.id;
        const fresh = id != null ? freshKeys[id] : undefined;
        const isFresh = fresh !== undefined;
        const revealed = id != null && revealedIds.has(id);
        const name = row.key_alias || maskKey(id);
        // What the inline chip displays:
        //   fresh        -> masked bullets, or the full sk- when revealed
        //   pre-existing -> the PUBLIC key id MASKED to prefix…last4 (compact;
        //                   maskKey returns the em-dash for a null id). The full
        //                   id is still copyable via the Copy action below.
        const chip = isFresh
          ? revealed
            ? fresh
            : MASKED_FRESH
          : maskKey(id);
        // The chip repeats the masked id beneath the name. Skip it for a
        // non-fresh key with NO alias — the name already IS the masked id, so
        // the two lines would otherwise be identical. Fresh keys always show it
        // (it carries the masked/revealed sk-).
        const showChip = isFresh || Boolean(row.key_alias);
        return (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-foreground truncate text-sm font-semibold">
              {name}
            </span>
            {showChip ? (
              <span
                data-slot="key-chip"
                data-revealed={isFresh && revealed ? '' : undefined}
                className={cn(
                  'font-mono text-xs break-all',
                  isFresh && revealed ? 'text-primary' : 'text-muted-foreground'
                )}
              >
                {chip}
              </span>
            ) : null}
          </div>
        );
      },
    },
    {
      key: 'created',
      header: 'Created',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => formatDate(row.created_at),
    },
    {
      key: 'lastused',
      header: 'Last used',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: () => EM_DASH,
    },
    {
      key: 'expires',
      header: 'Expires',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => (row.expires == null ? 'Never' : formatDate(row.expires)),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => {
        const { label, variant } = statusFor(row);
        return <Badge variant={variant}>{label}</Badge>;
      },
    },
  ];

  return (
    <DataTable
      data-slot="keys-table"
      columns={columns}
      rows={rows}
      getRowId={(row) => row.id ?? ''}
      empty={
        <div data-slot="keys-table-empty" className="py-6">
          <p className="text-foreground text-base font-semibold">No API Keys</p>
          <p className="text-muted-foreground mt-1 text-sm">
            You have no virtual keys yet. Create one to get started.
          </p>
        </div>
      }
      rowActions={(row) => {
        const id = row.id;
        const fresh = id != null ? freshKeys[id] : undefined;
        const isFresh = fresh !== undefined;
        const revealed = id != null && revealedIds.has(id);
        // Copy emits the full sk- for a fresh key, else the public id.
        const copyValue = isFresh ? fresh : (id ?? '');
        return (
          <div className="flex items-center justify-end gap-2">
            {isFresh && id != null ? (
              <button
                type="button"
                data-slot="key-reveal"
                aria-label={revealed ? 'Hide key' : 'Reveal'}
                title={revealed ? 'Hide key' : 'Reveal'}
                onClick={() => toggleReveal(id)}
                className={cn(
                  'inline-flex size-7 items-center justify-center rounded-md border transition-colors',
                  revealed
                    ? 'border-primary text-primary'
                    : 'text-muted-foreground hover:text-foreground border-border'
                )}
              >
                {revealed ? (
                  <EyeOff className="size-[15px]" aria-hidden="true" />
                ) : (
                  <Eye className="size-[15px]" aria-hidden="true" />
                )}
              </button>
            ) : null}
            <CopyButton value={copyValue} />
            <button
              type="button"
              data-slot="key-delete"
              aria-label="Revoke"
              title="Revoke"
              onClick={() => onDelete(row)}
              className="text-destructive border-destructive/40 hover:border-destructive inline-flex size-7 items-center justify-center rounded-md border transition-colors"
            >
              <Trash2 className="size-[15px]" aria-hidden="true" />
            </button>
          </div>
        );
      }}
    />
  );
}
