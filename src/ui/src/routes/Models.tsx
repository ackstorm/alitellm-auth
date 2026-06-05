// Models.tsx — the #/models catalog page (nav: KEYS · STATS · MODELS · MCP · HOW-TO).
//
// Read-only catalog of the model aliases available on the gateway, sourced from
// GET /api/session/models (server-side LiteLLM /model_group/info — the safe public
// group view: no upstream model / api_base / api_key). Per alias it shows the
// provider(s), mode, context window (max input/output tokens), per-1M-token
// pricing, and capability badges (vision / tools / reasoning / web).
//
// States mirror the Stats container: per-page error+retry card (useModels throws
// on non-200) and an empty "no models configured" state. Presentational only —
// no data ownership; the hook owns the fetch.

import {
  Brain,
  Eye,
  Globe,
  Wrench,
} from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { useModels } from '@/hooks/use-models';
import type { ModelRow } from '@/lib/api-types';
import { formatPricePerMillion, formatTokens } from '@/lib/format';

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

// Column captions (mono 11px section-label role).
const COLS = ['Model', 'Mode', 'Context (in / out)', '$ / 1M in', '$ / 1M out', 'Capabilities'];

// A small provider chip (e.g. openai, anthropic, google).
function ProviderChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-surface-elevated px-1.5 py-0.5 font-mono text-[10px] font-semibold lowercase tracking-wide text-text-secondary">
      {label}
    </span>
  );
}

// A capability badge: a tinted icon pill with a tooltip. Only rendered when the
// capability is true (off-capabilities are simply absent — no greyed clutter).
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
      className="inline-flex size-6 items-center justify-center rounded-md border border-primary/30 bg-primary/10 text-primary"
    >
      <Icon className="size-3.5" aria-hidden="true" />
    </span>
  );
}

function ModeBadge({ mode }: { mode: string | null }) {
  if (!mode) return <span className="text-text-tertiary">{EM_DASH}</span>;
  return (
    <span className="inline-flex items-center rounded-md border border-border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
      {mode}
    </span>
  );
}

function ContextCell({ row }: { row: ModelRow }) {
  const hasIn = typeof row.max_input_tokens === 'number';
  const hasOut = typeof row.max_output_tokens === 'number';
  if (!hasIn && !hasOut) return <span className="text-text-tertiary">{EM_DASH}</span>;
  return (
    <span className="font-mono text-xs whitespace-nowrap text-text-primary">
      {hasIn ? formatTokens(row.max_input_tokens) : EM_DASH}
      <span className="text-text-tertiary"> / </span>
      {hasOut ? formatTokens(row.max_output_tokens) : EM_DASH}
    </span>
  );
}

function ModelRowItem({ row }: { row: ModelRow }) {
  return (
    <tr className="border-b border-border last:border-0">
      {/* Model name + provider chips */}
      <td className="py-3 pr-4 align-top">
        <div className="font-mono text-sm font-medium text-text-primary">
          {row.name ?? EM_DASH}
        </div>
        {row.providers.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {row.providers.map((p) => (
              <ProviderChip key={p} label={p} />
            ))}
          </div>
        )}
      </td>
      {/* Mode */}
      <td className="py-3 pr-4 align-top">
        <ModeBadge mode={row.mode} />
      </td>
      {/* Context */}
      <td className="py-3 pr-4 align-top">
        <ContextCell row={row} />
      </td>
      {/* Input price */}
      <td className="py-3 pr-4 text-right align-top font-mono text-xs whitespace-nowrap text-text-primary">
        {formatPricePerMillion(row.input_cost_per_token)}
      </td>
      {/* Output price */}
      <td className="py-3 pr-4 text-right align-top font-mono text-xs whitespace-nowrap text-text-primary">
        {formatPricePerMillion(row.output_cost_per_token)}
      </td>
      {/* Capabilities */}
      <td className="py-3 align-top">
        <div className="flex flex-wrap gap-1.5">
          {row.supports_vision && <CapBadge icon={Eye} label="Vision" />}
          {row.supports_function_calling && (
            <CapBadge icon={Wrench} label="Function calling / tools" />
          )}
          {row.supports_reasoning && <CapBadge icon={Brain} label="Reasoning" />}
          {row.supports_web_search && <CapBadge icon={Globe} label="Web search" />}
          {!row.supports_vision &&
            !row.supports_function_calling &&
            !row.supports_reasoning &&
            !row.supports_web_search && (
              <span className="font-mono text-xs text-text-tertiary">{EM_DASH}</span>
            )}
        </div>
      </td>
    </tr>
  );
}

export function Models() {
  const query = useModels();
  const header = (
    <div>
      <h1 className="font-sans text-2xl font-semibold leading-snug text-text-primary">
        {PAGE_TITLE}
      </h1>
      <p className="mt-1 max-w-2xl font-sans text-sm text-text-secondary">
        {PAGE_SUB}
      </p>
    </div>
  );

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
      ) : models.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-border bg-surface p-12 text-center">
          <div className="font-sans text-lg font-semibold text-text-primary">
            {EMPTY_HEADING}
          </div>
          <div className="max-w-md font-sans text-sm text-text-secondary">
            {EMPTY_BODY}
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface px-5">
          <table className="w-full min-w-[680px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border">
                {COLS.map((c, i) => (
                  <th
                    key={c}
                    className={`py-3 pr-4 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary ${
                      i === 3 || i === 4 ? 'text-right' : ''
                    }`}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => (
                <ModelRowItem key={m.name ?? i} row={m} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
