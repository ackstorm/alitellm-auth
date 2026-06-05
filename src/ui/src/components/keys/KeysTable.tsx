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
import { Star, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import { useKeys, useMakeDefault } from '@/hooks/use-keys';
import { formatDate } from '@/lib/format';
import { isExpired, isRevoked, selectKeyRows } from '@/lib/keys';
import { cn } from '@/lib/utils';
import type { KeyRow } from '@/lib/api-types';

// The em-dash placeholder (matches format.ts EM_DASH) for the always-empty
// "Last used" cell (the backend emits no last-used — parity with the old table).
const EM_DASH = '—';

// How many leading characters of the public key id to show in the table.
const KEY_ID_MAX = 16;

// Display the public key id as up to KEY_ID_MAX leading chars, with a trailing
// ellipsis when it is longer (e.g. "9834338392932xjw…"). Prefix-truncated (NOT
// the prefix…last4 mask used elsewhere) per the keys-table design. The full id
// is intentionally not surfaced in the table.
function shortKeyId(id: string | null): string {
  if (id == null || id === '') return EM_DASH;
  return id.length > KEY_ID_MAX ? `${id.slice(0, KEY_ID_MAX)}…` : id;
}

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
  const makeDefault = useMakeDefault();
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
        const short = shortKeyId(row.id);
        // The primary line: the human alias when set, else the truncated id.
        const name = row.key_alias || short;
        // The chip repeats the truncated id beneath the name. Skip it when there
        // is no alias — the name already IS the truncated id, so the two lines
        // would otherwise be identical.
        const showChip = Boolean(row.key_alias);
        return (
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="flex min-w-0 items-center gap-2">
              <span className="text-foreground truncate text-sm font-semibold">
                {name}
              </span>
              {row.is_default ? (
                <Badge
                  data-slot="key-default-badge"
                  variant="default"
                  className="shrink-0 px-1.5 py-0 text-[10px] font-semibold tracking-wider"
                >
                  DEFAULT
                </Badge>
              ) : null}
            </div>
            {showChip ? (
              <span
                data-slot="key-chip"
                className="text-muted-foreground font-mono text-xs break-all"
              >
                id:{short}
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
          {row.is_default ? (
            <button
              type="button"
              data-slot="key-default-on"
              aria-label="Default key"
              title="This is your default key"
              disabled
              className="text-primary border-primary/40 inline-flex size-7 cursor-default items-center justify-center rounded-md border"
            >
              <Star className="size-[15px] fill-current" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="button"
              data-slot="key-make-default"
              aria-label="Make default"
              title="Make this your default key"
              onClick={() => makeDefault.mutate(row.id ?? '')}
              className="text-muted-foreground border-border hover:border-primary hover:text-primary inline-flex size-7 cursor-pointer items-center justify-center rounded-md border transition-colors"
            >
              <Star className="size-[15px]" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            data-slot="key-delete"
            aria-label="Revoke"
            title={
              row.is_default
                ? 'Make another key default before deleting'
                : 'Revoke'
            }
            disabled={row.is_default}
            onClick={() => onDelete(row)}
            className={cn(
              'inline-flex size-7 items-center justify-center rounded-md border transition-colors',
              row.is_default
                ? 'text-muted-foreground border-border cursor-not-allowed opacity-50'
                : 'text-destructive border-destructive/40 hover:border-destructive cursor-pointer'
            )}
          >
            <Trash2 className="size-[15px]" aria-hidden="true" />
          </button>
        </div>
      )}
    />
  );
}
