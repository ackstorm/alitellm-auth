// ModelFilters.tsx — capability quick-filter toggles above the models table.
import * as React from 'react';
import type { ModelRow } from '@/lib/api-types';

export type ModelCapKey = 'vision' | 'reasoning' | 'function_calling' | 'web_search';

const CAP_FIELD: Record<ModelCapKey, keyof ModelRow> = {
  vision: 'supports_vision',
  reasoning: 'supports_reasoning',
  function_calling: 'supports_function_calling',
  web_search: 'supports_web_search',
};

const CAP_LABEL: Record<ModelCapKey, string> = {
  vision: 'Vision',
  reasoning: 'Thinking',
  function_calling: 'Tools',
  web_search: 'Web',
};

// Keep only rows where EVERY active capability is supported (AND semantics).
export function applyModelFilters(rows: ModelRow[], active: Set<ModelCapKey>): ModelRow[] {
  if (active.size === 0) return rows;
  return rows.filter((r) => [...active].every((k) => Boolean(r[CAP_FIELD[k]])));
}

export function ModelFilters({
  active,
  onToggle,
  onClear,
}: {
  active: Set<ModelCapKey>;
  onToggle: (k: ModelCapKey) => void;
  onClear: () => void;
}): React.ReactElement {
  // "ALL" = no capability filter (the default). Selected whenever the active set
  // is empty; clicking it clears any active capability toggles.
  const allOn = active.size === 0;
  return (
    <div className="flex flex-wrap gap-1.5">
      <button
        type="button"
        aria-pressed={allOn}
        onClick={onClear}
        className={`cursor-pointer rounded-md border px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wide transition-colors ${
          allOn ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-secondary hover:border-primary'
        }`}
      >
        All
      </button>
      {(Object.keys(CAP_LABEL) as ModelCapKey[]).map((k) => {
        const on = active.has(k);
        return (
          <button
            key={k}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(k)}
            className={`cursor-pointer rounded-md border px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wide transition-colors ${
              on ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-secondary hover:border-primary'
            }`}
          >
            {CAP_LABEL[k]}
          </button>
        );
      })}
    </div>
  );
}
