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
import { MoreVertical, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';

import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  useKeys,
  useToggleKeyBlock,
} from '@/hooks/use-keys';
import { formatDate, formatInt } from '@/lib/format';
import { isBlocked, isExpired, isExternal, selectKeyRows } from '@/lib/keys';
import { isStale, relativeTime } from '@/lib/relative-time';
import { cn } from '@/lib/utils';
import type { KeyRow } from '@/lib/api-types';

// The em-dash placeholder (matches format.ts EM_DASH) for an empty "Last used"
// cell (the backend surfaces LiteLLM's per-key last_active; null until used).
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

/** Status precedence: Revoked > Disabled > Expired > Active (UI-SPEC §C4).
 *  "Disabled" is the reversible LiteLLM `blocked` state; "Revoked" is a true
 *  revoked flag (checked first, never emitted by the current backend). */
function statusFor(row: KeyRow): {
  label: 'Revoked' | 'Disabled' | 'Expired' | 'Active';
  variant: 'default' | 'outline' | 'destructive' | 'secondary';
} {
  if (row.revoked) return { label: 'Revoked', variant: 'destructive' };
  if (isBlocked(row)) return { label: 'Disabled', variant: 'secondary' };
  if (isExpired(row)) return { label: 'Expired', variant: 'outline' };
  return { label: 'Active', variant: 'default' };
}

// Sort precedence for the Status column (ascending = Active first, Revoked last;
// mirrors the status badge precedence rather than alphabetical order).
const STATUS_RANK: Record<ReturnType<typeof statusFor>['label'], number> = {
  Active: 0,
  Expired: 1,
  Disabled: 2,
  Revoked: 3,
};

export function KeysTable({ onDelete }: KeysTableProps): React.ReactElement {
  const query = useKeys();
  const toggleBlock = useToggleKeyBlock();
  const allRows = selectKeyRows(query.data);
  // External (pkid_/ekid_) keys are noise next to the user's own keys, so they
  // are hidden by default behind an explicit count toggle (not persisted).
  const [showExternal, setShowExternal] = React.useState(false);
  const externalCount = allRows.filter(isExternal).length;
  const rows = showExternal ? allRows : allRows.filter((k) => !isExternal(k));

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
      // the row action off the right edge under overflow-x-auto. max-w caps the
      // column so a long alias (e.g. foreign ekid_/pkid_ names) truncates instead
      // of forcing the whole table to scroll horizontally.
      className: 'align-top max-w-[220px]',
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
              {row.managed === false ? (
                // Minted elsewhere (ach's pkid_/ekid_ keys, listed here because
                // they carry this user_id). Muted, not accented: it explains why
                // the row's actions are missing, it is not a status to aspire to.
                <span
                  data-slot="key-external-badge"
                  className="text-muted-foreground inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide"
                  title="Created outside this console — managed by another service"
                >
                  EXTERNAL
                </span>
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
      sortAccessor: (row) => row.key_alias || row.id,
    },
    {
      key: 'created',
      header: 'Created',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => formatDate(row.created_at),
      sortAccessor: (row) => row.created_at,
    },
    {
      key: 'lastused',
      header: 'Last used',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => {
        const stale = isStale(row.last_used);
        return (
          <span
            data-slot="key-lastused"
            data-testid={stale ? 'key-lastused-stale' : 'key-lastused'}
            className={stale ? 'text-amber-600 dark:text-amber-400' : undefined}
            title={row.last_used ?? undefined}
          >
            {relativeTime(row.last_used)}
          </span>
        );
      },
      // Sort by the raw timestamp (null sorts last); null last_used = never used.
      sortAccessor: (row) => row.last_used,
    },
    {
      key: 'expires',
      header: 'Expires',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => (row.expires == null ? 'Never' : formatDate(row.expires)),
      sortAccessor: (row) => row.expires,
    },
    {
      key: 'limits',
      header: 'TPM / RPM',
      headerClassName: 'whitespace-nowrap',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => {
        const tpm = row.tpm_limit == null ? EM_DASH : formatInt(row.tpm_limit);
        const rpm = row.rpm_limit == null ? EM_DASH : formatInt(row.rpm_limit);
        return (
          <span className="text-text-secondary">
            {tpm} / {rpm}
          </span>
        );
      },
      sortAccessor: (row) => row.tpm_limit,
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => {
        const { label, variant } = statusFor(row);
        return <Badge variant={variant}>{label}</Badge>;
      },
      sortAccessor: (row) => STATUS_RANK[statusFor(row).label],
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <DataTable
        data-slot="keys-table"
        columns={columns}
        rows={rows}
        // Default sort so the active-sort marker shows on load (newest keys first);
        // every other column header stays click-to-sort.
        defaultSort={{ key: 'created', dir: 'desc' }}
        getRowId={(row) => row.id ?? ''}
        // Dim a disabled (blocked) row so it reads as inactive at a glance (the
        // kebab is portaled to <body>, so its Enable item stays full opacity).
        rowClassName={(row) => cn(row.blocked && 'opacity-40')}
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
          <div className="flex justify-end">
            {/* Single per-row control — a kebab menu. Revoke lives INSIDE it (as a
                destructive item) rather than as an always-visible red trash on
                every row, so the table doesn't read as "delete everything". */}
            <DropdownMenu>
              <DropdownMenuTrigger
                data-slot="key-menu"
                aria-label="More actions"
                className="text-muted-foreground border-border hover:border-primary hover:text-primary inline-flex size-7 cursor-pointer items-center justify-center rounded-md border transition-colors outline-none focus-visible:border-primary"
              >
                <MoreVertical className="size-[15px]" aria-hidden="true" />
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                {/* Foreign keys (managed === false, e.g. ekid_/pkid_) are locked:
                    only Disable/Enable is offered. Revoke is hidden — the backend
                    also 409s it. */}
                {row.managed === false ? (
                  <>
                    <DropdownMenuItem disabled data-slot="key-unmanaged">
                      Managed externally
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                {/* Disable/Enable — reversible LiteLLM block. Any key may be
                    disabled, foreign ones included. */}
                <DropdownMenuItem
                  data-slot="key-toggle-block"
                  onSelect={() =>
                    toggleBlock.mutate({ id: row.id ?? '', blocked: !row.blocked })
                  }
                >
                  {row.blocked ? 'Enable key' : 'Disable key'}
                </DropdownMenuItem>
                {/* Revoke — destructive; hidden on foreign keys (this service does
                    not own their provisioning). */}
                {row.managed !== false ? (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      data-slot="key-delete"
                      onSelect={() => onDelete(row)}
                      className="text-destructive focus:bg-destructive/10 focus:text-destructive"
                    >
                      <Trash2 aria-hidden="true" />
                      Revoke key
                    </DropdownMenuItem>
                  </>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      />
      {externalCount > 0 ? (
        <button
          type="button"
          data-slot="keys-external-toggle"
          aria-pressed={showExternal}
          onClick={() => setShowExternal((v) => !v)}
          className="flex cursor-pointer items-center gap-1 self-start font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary transition-colors hover:text-text-primary"
        >
          <span
            aria-hidden="true"
            className={`inline-block size-0 border-y-[4px] border-l-[6px] border-y-transparent border-l-current transition-transform ${showExternal ? 'rotate-90' : ''}`}
          />
          <span>
            {showExternal ? 'Hide external keys' : `Show external keys (${externalCount})`}
          </span>
        </button>
      ) : null}
    </div>
  );
}
