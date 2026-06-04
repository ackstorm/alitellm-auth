// ModelTable.tsx — the Model Breakdown DATA-TABLE for the #/stats Usage & Spend
// page (STATS-06). React + Tailwind, rendered through the generic DataTable<T>.
// Port of the old Preact leaf src/ui/stats-model-table.js.
//
// PRESENTATIONAL LEAF: it receives the Phase-12 `models[]` slice + the
// `capabilities` map. No fetch, no data ownership.
//
// `null` ≠ `0` (Phase-12 D-08): an unavailable figure renders em-dash, never 0.
// Capability-driven cells (D-15): token_split === false -> INPUT/OUTPUT cells
// em-dash; per_model_last_used === false -> the whole LAST USED column em-dash.
// Rows are sorted SPEND descending (UI-SPEC §6 — matches the donut's narrative).
//
// SECURITY (T-13-08, XSS): every cell value renders as a React text child
// (auto-escaped). No dangerouslySetInnerHTML.

import * as React from 'react';

import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import type { StatsCapabilities, StatsModelRow } from '@/lib/api-types';
import { abbreviate, formatCurrency, formatDate, formatInt } from '@/lib/format';

// The em-dash placeholder (matches format.ts EM_DASH) — every null / unavailable
// / capability-disabled cell renders THIS, never a `0`.
const EM_DASH = '—';

// The locked empty copy (UI-SPEC §Copywriting Contract / §6).
const EMPTY_COPY = 'No usage in this range';

// Render the contract's `spend_pct` fraction as a one-decimal `%` (UI-SPEC
// §Typography: 0.182 -> "18.2%"); a null / non-finite fraction -> em-dash.
function formatPct(fraction: number | null | undefined): string {
  if (typeof fraction !== 'number' || !Number.isFinite(fraction)) return EM_DASH;
  return `${(fraction * 100).toFixed(1)}%`;
}

export interface ModelTableProps {
  /** The Phase-12 `models[]` slice. */
  models: StatsModelRow[] | null | undefined;
  /** The contract `capabilities` map (token_split, per_model_last_used, …). A
   *  missing entry is treated as AVAILABLE — only an explicit `false` collapses
   *  a column. */
  capabilities: StatsCapabilities | null | undefined;
}

export function ModelTable({
  models,
  capabilities,
}: ModelTableProps): React.ReactElement {
  const caps = capabilities ?? null;
  const tokenSplit = caps?.token_split;
  const perModelLastUsed = caps?.per_model_last_used;

  const rows = Array.isArray(models) ? models : [];

  // Default sort: SPEND descending (UI-SPEC §6). Copy before sorting so the
  // parent's array is never mutated; a non-numeric spend sorts last (-Infinity).
  const spendOf = (m: StatsModelRow) =>
    typeof m.spend === 'number' && Number.isFinite(m.spend) ? m.spend : -Infinity;
  const sorted = rows.slice().sort((a, b) => spendOf(b) - spendOf(a));

  // The LOCKED 8-column order (UI-SPEC §6). Numeric columns right-aligned; MODEL
  // and LAST USED left-aligned (mirrors the old smt-cell-model/lastused idiom).
  const columns: DataTableColumn<StatsModelRow>[] = [
    {
      key: 'model',
      header: 'MODEL',
      className: 'font-mono text-xs text-text-primary',
      cell: (m) => (m.model == null ? EM_DASH : m.model),
    },
    {
      key: 'requests',
      header: 'REQUESTS',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => formatInt(m.requests),
    },
    {
      key: 'input',
      header: 'INPUT',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => (tokenSplit === false ? EM_DASH : abbreviate(m.input_tokens)),
    },
    {
      key: 'output',
      header: 'OUTPUT',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => (tokenSplit === false ? EM_DASH : abbreviate(m.output_tokens)),
    },
    {
      key: 'total',
      header: 'TOTAL',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => abbreviate(m.total_tokens),
    },
    {
      key: 'spend',
      header: 'SPEND',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => formatCurrency(m.spend),
    },
    {
      key: '%spend',
      header: '% SPEND',
      headerClassName: 'text-right',
      className: 'font-mono text-xs text-right whitespace-nowrap',
      cell: (m) => formatPct(m.spend_pct),
    },
    {
      key: 'lastused',
      header: 'LAST USED',
      className: 'font-mono text-xs whitespace-nowrap',
      cell: (m) =>
        perModelLastUsed === false ? EM_DASH : formatDate(m.last_used),
    },
  ];

  return (
    <DataTable
      data-slot="model-table"
      columns={columns}
      rows={sorted}
      getRowId={(m) => m.model ?? ''}
      empty={
        <div data-slot="model-table-empty">
          <p className="text-text-secondary text-sm">{EMPTY_COPY}</p>
        </div>
      }
    />
  );
}
