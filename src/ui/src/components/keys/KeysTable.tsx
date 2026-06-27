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
import { Button } from '@/components/ui/button';
import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  useChangeKeyTeam,
  useKeys,
  useMakeDefault,
  useToggleKeyBlock,
} from '@/hooks/use-keys';
import { useTeams } from '@/hooks/use-teams';
import { formatDate } from '@/lib/format';
import { isBlocked, isExpired, selectKeyRows } from '@/lib/keys';
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
  const makeDefault = useMakeDefault();
  const toggleBlock = useToggleKeyBlock();
  // Teams the user may move a key into. [] when teams are unavailable — the
  // Change-team action is then hidden entirely (single-team deployments).
  const teams = useTeams().data ?? [];
  const changeTeam = useChangeKeyTeam();
  // The change-team dialog target (null = closed) + the picked team id.
  const [changing, setChanging] = React.useState<KeyRow | null>(null);
  const [pickedTeam, setPickedTeam] = React.useState('');
  const rows = selectKeyRows(query.data);

  // Resolve a key's team_id to its display alias (matching the picker / change
  // dialog / dashboard tile, which all show aliases). Falls back to the raw id
  // when teams aren't loaded or the id has no match, then EM_DASH when null.
  const teamAlias = (id: string | null): string =>
    (id ? teams.find((t) => t.id === id)?.alias : null) ?? id ?? EM_DASH;

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
                // Neutral GREY pill — DEFAULT is a property of the key, not a
                // status, so it matches the muted catalog pills used elsewhere
                // (e.g. the Models table) rather than the green accent badge.
                <span
                  data-slot="key-default-badge"
                  className="inline-flex shrink-0 items-center rounded-md border border-border bg-surface-elevated px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-text-secondary"
                >
                  DEFAULT
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
      cell: (row) => (row.last_used == null ? EM_DASH : formatDate(row.last_used)),
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
      key: 'team',
      header: 'Team',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (row) => teamAlias(row.team_id),
      sortAccessor: (row) => teamAlias(row.team_id),
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

  // Explicit-only nudge: the user has keys but has not picked a default yet.
  // A default is never auto-assigned, and Chat is gated on having one — so prompt.
  const showDefaultNudge = rows.length > 0 && !rows.some((r) => r.is_default);

  return (
    <div className="flex flex-col gap-3">
      {showDefaultNudge ? (
        <div
          data-slot="keys-default-nudge"
          className="border-primary/30 bg-primary/5 text-foreground rounded-lg border px-3 py-2 text-xs"
        >
          No default key set. Open a key&apos;s{' '}
          <MoreVertical className="inline size-3 align-[-1px]" aria-hidden="true" />{' '}
          menu and choose <span className="font-semibold">Set as default</span> to
          enable Chat.
        </div>
      ) : null}
      <DataTable
        data-slot="keys-table"
        columns={columns}
        rows={rows}
        // Default sort so the active-sort marker shows on load (newest keys first);
        // every other column header stays click-to-sort.
        defaultSort={{ key: 'created', dir: 'desc' }}
        getRowId={(row) => row.id ?? ''}
        // Dim a disabled (blocked) row so it reads as inactive at a glance. The
        // kebab content is portaled to <body>, so its Enable item stays full
        // opacity even though the trigger is dimmed with the row.
        rowClassName={(row) => (row.blocked ? 'opacity-40' : undefined)}
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

            {/* Kebab menu — per-row actions beyond Revoke. "Set as default" is the
                only item today (omitted on the default key, which shows a disabled
                marker so the menu is never empty). Room for more (e.g. Disable). */}
            <DropdownMenu>
              <DropdownMenuTrigger
                data-slot="key-menu"
                aria-label="More actions"
                className="text-muted-foreground border-border hover:border-primary hover:text-primary inline-flex size-7 cursor-pointer items-center justify-center rounded-md border transition-colors outline-none focus-visible:border-primary"
              >
                <MoreVertical className="size-[15px]" aria-hidden="true" />
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                {row.is_default ? (
                  <DropdownMenuItem disabled data-slot="key-is-default">
                    Default key
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem
                    data-slot="key-set-default"
                    onSelect={() => makeDefault.mutate(row.id ?? '')}
                  >
                    Set as default
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                {/* Disable/Enable — reversible LiteLLM block. Any key may be
                    disabled, including the default (Chat then stays gated until
                    re-enabled). */}
                <DropdownMenuItem
                  data-slot="key-toggle-block"
                  onSelect={() =>
                    toggleBlock.mutate({ id: row.id ?? '', blocked: !row.blocked })
                  }
                >
                  {row.blocked ? 'Enable key' : 'Disable key'}
                </DropdownMenuItem>
                {/* Change team — only when the user belongs to >1 team; opens
                    the dialog seeded with the row's current team. */}
                {teams.length > 0 ? (
                  <DropdownMenuItem
                    data-slot="key-change-team"
                    onSelect={() => {
                      setChanging(row);
                      setPickedTeam(row.team_id ?? '');
                    }}
                  >
                    Change team…
                  </DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      />

      {/* Change-team dialog. Controlled by `changing` (null = closed). The team
          picker is a native <select> styled to match Input (no shadcn Select in
          this project); Save is gated to a real, different team. */}
      <Dialog
        open={changing !== null}
        onOpenChange={(o) => {
          if (!o) setChanging(null);
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Change team</DialogTitle>
          </DialogHeader>
          <select
            aria-label="Team"
            value={pickedTeam}
            onChange={(e) => setPickedTeam(e.target.value)}
            className="border-input dark:bg-input/30 h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
          >
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.alias}
              </option>
            ))}
          </select>
          <div className="flex justify-end gap-3">
            <Button type="button" variant="outline" onClick={() => setChanging(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={
                changeTeam.isPending ||
                pickedTeam === '' ||
                pickedTeam === changing?.team_id
              }
              onClick={() => {
                changeTeam.mutate({ id: changing!.id ?? '', teamId: pickedTeam });
                setChanging(null);
              }}
            >
              Save
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
