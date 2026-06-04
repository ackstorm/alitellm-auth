// KeysTable.tsx — the keys-as-DATA-TABLE surface for the alitellm-auth console
// (DASH-02 / DASH-03 / DASH-06). React + Tailwind, rendered through the generic
// DataTable<T>. Parity reference: src/ui/keys-table.js.
//
// Unlike the old presentational leaf, this component OWNS its data: it calls
// useKeys() internally. The actual DELETE + confirm modal is wired by the
// parent (Dashboard); KeysTable only invokes onDelete(row) from the per-row
// revoke action.
//
// SCOPE NOTE: the old table's chevron-expandable per-key usage-detail row
// (Spend/TPM/RPM/Budget) and the client-side "Showing X of Y" pagination are
// intentionally OUT OF SCOPE here (tracked as a known parity gap) — the generic
// DataTable is single-row-per-item.
//
// SECURITY INVARIANTS (threat register 10-03 / 14-03):
//   • The table NEVER renders a secret. The full sk- of a freshly-created key is
//     shown exactly once, in the create-key modal at mint time ("you won't see
//     it again"); from then on the table shows only the PUBLIC key id, masked to
//     prefix…last4. There is no reveal and no copy action here — both were
//     redundant with the one-time create-modal reveal and have been removed.

import * as React from 'react';
import { Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import { useKeys } from '@/hooks/use-keys';
import { formatDate, maskKey } from '@/lib/format';
import { isExpired, isRevoked, selectKeyRows } from '@/lib/keys';
import type { KeyRow } from '@/lib/api-types';

// The em-dash placeholder (matches format.ts EM_DASH) for the always-empty
// "Last used" cell (the backend emits no last-used — parity with the old table).
const EM_DASH = '—';

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

export function KeysTable({ onDelete }: KeysTableProps): React.ReactElement {
  const query = useKeys();
  const rows = selectKeyRows(query.data);

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
      // align-top (the cell is a two-line stack). The PUBLIC key id is shown
      // MASKED to a short prefix…last4 (maskKey) — the full 64-char hash would
      // force the table wider than the ~800px main column and scroll Status +
      // the row action off the right edge under overflow-x-auto.
      className: 'align-top',
      cell: (row) => {
        const id = row.id;
        // The primary line: the human alias when set, else the masked id.
        const name = row.key_alias || maskKey(id);
        // The chip repeats the masked id beneath the name. Skip it when there is
        // no alias — the name already IS the masked id, so the two lines would
        // otherwise be identical.
        const showChip = Boolean(row.key_alias);
        return (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-foreground truncate text-sm font-semibold">
              {name}
            </span>
            {showChip ? (
              <span
                data-slot="key-chip"
                className="text-muted-foreground font-mono text-xs break-all"
              >
                id:{maskKey(id)}
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
      actionsHeader="Action"
      empty={
        <div data-slot="keys-table-empty" className="py-6">
          <p className="text-foreground text-base font-semibold">No API Keys</p>
          <p className="text-muted-foreground mt-1 text-sm">
            You have no virtual keys yet. Create one to get started.
          </p>
        </div>
      }
      rowActions={(row) => (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            data-slot="key-delete"
            aria-label="Revoke"
            title="Revoke"
            onClick={() => onDelete(row)}
            className="text-destructive border-destructive/40 hover:border-destructive inline-flex size-7 cursor-pointer items-center justify-center rounded-md border transition-colors"
          >
            <Trash2 className="size-[15px]" aria-hidden="true" />
          </button>
        </div>
      )}
    />
  );
}
