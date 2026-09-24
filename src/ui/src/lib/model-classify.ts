// model-classify.ts — pure row classification for the models catalog + the
// stats "Usage Breakdown" table (LiteLLM lumps MCP tool spend into the model
// breakdown under an "MCP: " prefix).
import type { ModelRow } from '@/lib/api-types';

export function isRouterModel(row: Pick<ModelRow, 'providers'>): boolean {
  return (row.providers ?? []).some((p) => String(p).toLowerCase() === 'auto_router');
}

// Agents shown as model rows: the operator's `agent.<name>` (→ a2a1/<name>) and
// LiteLLM's own `a2a/<name>`, which /model_group/info appends for every agent the
// key can reach (append_agents_to_model_group). They are listed on the A2A page,
// not in the Models catalog.
export function isAgentModelRow(name: string | null | undefined): boolean {
  return typeof name === 'string' && (name.startsWith('agent.') || name.startsWith('a2a/'));
}

const MCP_PREFIX = 'MCP:';

export function isMcpModelRow(name: string | null | undefined): boolean {
  return typeof name === 'string' && name.trim().startsWith(MCP_PREFIX);
}

// Strip the "MCP: " prefix for display; returns the input unchanged if absent.
export function mcpToolLabel(name: string | null | undefined): string {
  if (!isMcpModelRow(name)) return name ?? '';
  return (name as string).slice((name as string).indexOf(MCP_PREFIX) + MCP_PREFIX.length).trim();
}
