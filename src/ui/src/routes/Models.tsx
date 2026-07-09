// Models.tsx — the #/models catalog page (nav: KEYS · MODELS · MCPS · STATS · HOW-TO).
//
// Read-only catalog of the model aliases available on the gateway, sourced from
// GET /api/session/models (server-side LiteLLM /model_group/info — the safe public
// group view: no upstream model / api_base / api_key). Per alias it shows the
// provider(s), mode, whether it is a thinking/reasoning model, context window
// (max input/output tokens), per-1M-token pricing, and capability badges.
//
// Renders through the SAME generic DataTable<T> as the Keys table so the two
// surfaces are visually coherent (header font/size, padding, row borders, card
// chrome). States: per-page error+retry card (useModels throws on non-200), a
// skeleton while pending, and an in-table empty state. Presentational only — no
// data ownership; the hook owns the fetch.

import {
  Brain,
  Eye,
  Globe,
  Wrench,
} from 'lucide-react';

import { useState } from 'react';

import { RequiresDefaultKey } from '@/components/layout/RequiresDefaultKey';
import {
  ModelFilters,
  applyModelFilters,
  type ModelCapKey,
} from '@/components/models/ModelFilters';
import {
  DataTable,
  type DataTableColumn,
} from '@/components/ui/data-table';
import { Skeleton } from '@/components/ui/skeleton';
import { useHasDefaultKey } from '@/hooks/use-keys';
import { useModels } from '@/hooks/use-models';
import type { ModelRow } from '@/lib/api-types';
import { formatPricePerMillion, formatTokens } from '@/lib/format';
import { isRouterModel } from '@/lib/model-classify';

const EM_DASH = '—';

const PAGE_TITLE = 'Models';
const PAGE_SUB =
  'Model aliases available on the gateway — pricing is per 1M tokens, context is the max input / output window.';
const ERR_HEADING = "Couldn't load models";
const ERR_BODY =
  "We couldn't reach the model catalog. Check your connection and retry.";
const EMPTY_HEADING = 'No models yet';
const EMPTY_BODY =
  'No model aliases are configured on the gateway for your access level.';

// A small provider chip (e.g. openai, anthropic, google). UPPERCASE to match
// the sibling Mode / Thinking / capability tags in the same row (was the lone
// lowercase chip — the casing drift flagged in the design review).
function ProviderChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-surface-elevated px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
      {label}
    </span>
  );
}

// A capability badge: a NEUTRAL grey icon pill with a tooltip. Grey (not the
// primary accent) so it reads as a static info marker, not a clickable/toggle
// button. Only rendered when the capability is true (off-capabilities are simply
// absent — no greyed clutter).
function CapBadge({
  icon: Icon,
  label,
}: {
  icon: typeof Eye;
  label: string;
}) {
  return (
    <span
      title={label}
      aria-label={label}
      className="inline-flex size-6 items-center justify-center rounded-md border border-border bg-surface-elevated text-text-secondary"
    >
      <Icon className="size-3.5" aria-hidden="true" />
    </span>
  );
}

// Thinking-column cell. Its own column (after Mode) answers "is this a reasoning
// model?" directly. Backed by supports_reasoning: a neutral labelled badge when
// true, an em-dash when not. Neutral styling — info, not a button.
function ThinkingCell({ on }: { on: boolean }) {
  if (!on) return <span className="text-muted-foreground">{EM_DASH}</span>;
  return (
    <span
      title="Thinking model — supports extended reasoning"
      aria-label="Thinking model"
      className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-elevated px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-text-secondary"
    >
      <Brain className="size-3" aria-hidden="true" />
      Yes
    </span>
  );
}

function ModeBadge({ mode }: { mode: string | null }) {
  if (!mode) return <span className="text-muted-foreground">{EM_DASH}</span>;
  return (
    <span className="inline-flex items-center rounded-md border border-border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
      {mode}
    </span>
  );
}

// Context window as "in / out", abbreviated (e.g. 128K / 16K). A single em-dash
// when neither cap is set.
function ContextCell({ row }: { row: ModelRow }) {
  if (isRouterModel(row)) {
    return (
      <span className="text-muted-foreground" title="Depends on the routed model">
        Dynamic
      </span>
    );
  }
  const hasIn = typeof row.max_input_tokens === 'number';
  const hasOut = typeof row.max_output_tokens === 'number';
  if (!hasIn && !hasOut) return <span className="text-muted-foreground">{EM_DASH}</span>;
  return (
    <span className="font-mono text-xs whitespace-nowrap text-foreground">
      {hasIn ? formatTokens(row.max_input_tokens) : EM_DASH}
      <span className="text-muted-foreground"> / </span>
      {hasOut ? formatTokens(row.max_output_tokens) : EM_DASH}
    </span>
  );
}

// Combined price cell: "$in / $out" per 1M tokens, mirroring ContextCell so the
// two paired metrics read the same way. A single em-dash when neither cost is set.
function PriceCell({ row }: { row: ModelRow }) {
  if (isRouterModel(row)) {
    return (
      <span className="text-muted-foreground" title="Priced by the routed model">
        Dynamic
      </span>
    );
  }
  const hasIn = typeof row.input_cost_per_token === 'number';
  const hasOut = typeof row.output_cost_per_token === 'number';
  if (!hasIn && !hasOut) return <span className="text-muted-foreground">{EM_DASH}</span>;
  return (
    <span className="font-mono text-xs whitespace-nowrap text-foreground">
      {hasIn ? formatPricePerMillion(row.input_cost_per_token) : EM_DASH}
      <span className="text-muted-foreground"> / </span>
      {hasOut ? formatPricePerMillion(row.output_cost_per_token) : EM_DASH}
    </span>
  );
}

// Capability badge cluster (vision / tools / web). Reasoning lives in its own
// Thinking column, so it is intentionally absent here.
function CapabilitiesCell({ row }: { row: ModelRow }) {
  const any =
    row.supports_vision || row.supports_function_calling || row.supports_web_search;
  return (
    <div className="flex flex-wrap gap-1.5">
      {row.supports_vision && <CapBadge icon={Eye} label="Vision" />}
      {row.supports_function_calling && (
        <CapBadge icon={Wrench} label="Function calling / tools" />
      )}
      {row.supports_web_search && <CapBadge icon={Globe} label="Web search" />}
      {!any && <span className="font-mono text-xs text-muted-foreground">{EM_DASH}</span>}
    </div>
  );
}

// Columns for the shared DataTable. Same contract as KeysTable so the two tables
// render with identical header/cell chrome.
const COLUMNS: DataTableColumn<ModelRow>[] = [
  {
    key: 'model',
    header: 'Model',
    headerClassName: 'whitespace-nowrap',
    className: 'align-top',
    cell: (row) => (
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-foreground font-mono text-sm font-semibold">
          {row.name ?? EM_DASH}
        </span>
        {row.providers.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {row.providers.map((p) => (
              <ProviderChip key={p} label={p} />
            ))}
          </div>
        ) : null}
      </div>
    ),
    sortAccessor: (row) => row.name,
  },
  {
    key: 'mode',
    header: 'Mode',
    className: 'align-top',
    cell: (row) => <ModeBadge mode={row.mode} />,
    sortAccessor: (row) => row.mode,
  },
  {
    key: 'thinking',
    header: 'Thinking',
    className: 'align-top',
    cell: (row) => <ThinkingCell on={row.supports_reasoning} />,
    sortAccessor: (row) => (row.supports_reasoning ? 1 : 0),
  },
  {
    key: 'context',
    header: 'Context (in / out)',
    headerClassName: 'whitespace-nowrap',
    className: 'align-top whitespace-nowrap',
    cell: (row) => <ContextCell row={row} />,
    sortAccessor: (row) => row.max_input_tokens,
  },
  {
    key: 'price',
    header: '$ / 1M (in / out)',
    headerClassName: 'whitespace-nowrap',
    className: 'align-top whitespace-nowrap',
    cell: (row) => <PriceCell row={row} />,
    sortAccessor: (row) => row.input_cost_per_token,
  },
  {
    key: 'caps',
    header: 'Capabilities',
    className: 'align-top',
    cell: (row) => <CapabilitiesCell row={row} />,
    // Sort by how many capabilities the model supports (most-capable first when
    // descending). Vision + function-calling + reasoning + web-search.
    sortAccessor: (row) =>
      [
        row.supports_vision,
        row.supports_function_calling,
        row.supports_reasoning,
        row.supports_web_search,
      ].filter(Boolean).length,
  },
];

export function Models() {
  // Per-user catalog: gated on a default key (the gateway scopes the read through
  // it). No default → render the prompt and DON'T fetch (useModels disabled).
  const hasDefault = useHasDefaultKey();
  const query = useModels(hasDefault);
  const [caps, setCaps] = useState<Set<ModelCapKey>>(new Set());
  const toggleCap = (k: ModelCapKey) =>
    setCaps((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  const header = (
    <div>
      <h1 className="font-sans text-2xl font-semibold leading-snug text-text-primary">
        {PAGE_TITLE}
      </h1>
      <p className="mt-1 font-sans text-sm text-text-secondary">
        {PAGE_SUB}
      </p>
    </div>
  );

  // No default key → calm "set a default" prompt (no request fired).
  if (!hasDefault) {
    return (
      <div className="flex flex-col gap-8">
        {header}
        <RequiresDefaultKey subject="Models" />
      </div>
    );
  }

  // Error (502 / network) — same card + retry as the Stats page.
  if (query.isError) {
    return (
      <div className="flex flex-col gap-8">
        {header}
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-surface p-12 text-center">
          <div className="font-sans text-2xl font-semibold text-text-primary">
            {ERR_HEADING}
          </div>
          <div className="max-w-md font-sans text-sm text-text-secondary">
            {ERR_BODY}
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-destructive px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wide text-destructive transition-colors hover:bg-destructive/10"
          >
            retry
          </button>
        </div>
      </div>
    );
  }

  const models = query.data?.models ?? [];

  return (
    <div className="flex flex-col gap-8">
      {header}

      {query.isPending ? (
        <Skeleton variant="table-rows" rows={6} />
      ) : (
        <div className="flex flex-col gap-3">
          <ModelFilters active={caps} onToggle={toggleCap} />
        <DataTable
          data-slot="models-table"
          columns={COLUMNS}
          rows={applyModelFilters(models, caps)}
          defaultSort={{ key: 'model', dir: 'asc' }}
          getRowId={(row) => row.name ?? ''}
          empty={
            <div data-slot="models-table-empty" className="py-6">
              <p className="text-foreground text-base font-semibold">
                {EMPTY_HEADING}
              </p>
              <p className="text-muted-foreground mt-1 text-sm">{EMPTY_BODY}</p>
            </div>
          }
        />
        </div>
      )}
    </div>
  );
}
