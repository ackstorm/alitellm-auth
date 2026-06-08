// HowTo.tsx — the "How-to" onboarding guide (nav: KEYS | STATS | HOW-TO).
//
// Answers the "I just logged in and minted a key — now what?" question for a
// corporate user. Three sections, all STATIC (no backend, no fetch):
//
//   §1 Quickstart  — mint a key (link to the Keys tab) + a copy-paste `curl` to
//                    the `ackstorm.fast` model alias against the user's gateway.
//   §2 Editors/CLI — tabbed setup for Claude Code / Gemini / opencode / codex /
//                    GitHub Copilot / Qwen Code (env exports, except the JSON-config
//                    tools); each links the authoritative LiteLLM guide where one exists.
//   §3 MCP servers — connect MCP clients to the gateway's /mcp endpoint (same key);
//                    optional x-mcp-servers header / group URL to scope the tools.
//   §4 No terminal — chat-UI cards (ACKstorm Chat, hosted; openwork, coming soon).
//
// PERSONALIZATION (no rebuild): the gateway base URL is read live from the
// session (`me.endpoint` === settings.api_public_url, e.g. https://api.<domain>);
// the hosted-chat URL is derived by swapping the `api.` host label for `chat.`
// (the deployment's convention — chat.<domain>). Falls back to a neutral
// placeholder host when the endpoint is absent/unparseable.
//
// SECURITY (T-10-01 / info disclosure): this page NEVER renders a real key. The
// curl/exports show the literal `sk-...` placeholder; minting (and the one-time
// `sk-` reveal) happens only on the Keys tab. Copy buttons write exactly the
// shown text on an explicit click (useCopyFeedback) — no auto-copy, no logging.

import { useState } from 'react';
import {
  ArrowRight,
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  MessageSquare,
  Server,
  Terminal,
} from 'lucide-react';
import { useNavigate } from 'react-router';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useCopyFeedback } from '@/hooks/use-copy-feedback';
import { cn } from '@/lib/utils';
import { deriveSubdomainUrl } from '@/lib/urls';
import { useConfigStore } from '@/stores/config';
import { useSessionStore } from '@/stores/session';

// The literal key placeholder shown everywhere a real `sk-` would go. The real
// key is shown ONCE, at creation, on the Keys tab — never on this page.
const KEY_PLACEHOLDER = 'sk-...';

// Featured model alias for the quickstart (locked copy — the standard alias).
const MODEL_ALIAS = 'ackstorm.fast';

// LiteLLM auth header (the deployment's standard: a Bearer value under the
// custom header name, not the bare Authorization header).
const AUTH_HEADER = 'x-litellm-api-key';

// Fallback host shown before the session endpoint resolves / when unparseable.
const FALLBACK_API_BASE = 'https://api.your-domain.example';

// `deriveSubdomainUrl` now lives in @/lib/urls (shared with the CHAT nav button).

// ── TOC ──────────────────────────────────────────────────────────────────────
// Sticky in-page nav. NOTE: this app is a HASH router (#/howto), so the URL hash
// belongs to react-router — we must NOT use `<a href="#id">` anchors (that would
// hijack the route hash). Instead each item scrolls its section into view.
const TOC = [
  { id: 'quickstart', label: 'Quickstart' },
  { id: 'tools', label: 'Editors & CLIs' },
  { id: 'mcp', label: 'MCP servers' },
  { id: 'chat', label: 'No terminal?' },
] as const;

function scrollToSection(id: string): void {
  document
    .getElementById(id)
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── CodeBlock ──────────────────────────────────────────────────────────────—─
// A dark, horizontally-scrollable code box with a copy button. `code` is shown
// verbatim (mono, pre-wrapped); the copy writes exactly that string. An optional
// `caption` renders a thin header strip (e.g. a shell/file label).
function CodeBlock({ code, caption }: { code: string; caption?: string }) {
  const { copied, copy } = useCopyFeedback();
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-background">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-surface px-3 py-1.5">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          {caption ?? 'shell'}
        </span>
        <button
          type="button"
          onClick={() => void copy(code)}
          className={cn(
            'inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11px] font-semibold lowercase tracking-wide transition-colors',
            copied
              ? 'border-primary bg-primary/15 text-primary'
              : 'border-border text-text-tertiary hover:border-primary hover:text-primary'
          )}
        >
          {copied ? (
            <Check className="size-3" aria-hidden="true" />
          ) : (
            <Copy className="size-3" aria-hidden="true" />
          )}
          {copied ? 'copied!' : 'copy'}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 font-mono text-[13px] leading-relaxed text-text-primary">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ── Section ──────────────────────────────────────────────────────────────────
// A titled content block with a scroll anchor (`id`) the TOC targets. `scroll-mt`
// keeps the heading clear of the top edge when scrolled into view.
function Section({
  id,
  icon: Icon,
  title,
  sub,
  children,
}: {
  id: string;
  icon: typeof Terminal;
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-8">
      <div className="flex items-center gap-2.5">
        <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-border">
          <Icon className="size-4 text-primary" aria-hidden="true" />
        </span>
        <h2 className="font-sans text-lg font-semibold leading-tight text-text-primary">
          {title}
        </h2>
      </div>
      <p className="mt-2 font-sans text-sm leading-relaxed text-text-secondary">
        {sub}
      </p>
      <div className="mt-5">{children}</div>
    </section>
  );
}

// A small numbered step marker (the quickstart 1·2 sequence).
function StepBadge({ n }: { n: number }) {
  return (
    <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full border border-primary/40 bg-primary/10 font-mono text-[11px] font-semibold text-primary">
      {n}
    </span>
  );
}

export function HowTo() {
  const me = useSessionStore((s) => s.me);
  const config = useConfigStore((s) => s.config);
  const navigate = useNavigate();

  // Live gateway base (api_public_url). Falls back to a neutral placeholder so
  // the page reads sensibly before the session resolves.
  const apiBase = me?.endpoint || FALLBACK_API_BASE;
  const chatUrl =
    config.chat_public_url || deriveSubdomainUrl(me?.endpoint, 'chat');
  const brandShort = config.brand_short || 'LiteLLM';

  // The quickstart curl — the featured first call. Header is the deployment's
  // standard `x-litellm-api-key: Bearer sk-...` form; the key is the placeholder.
  const curlSnippet = `curl ${apiBase}/v1/chat/completions \\
  -H "${AUTH_HEADER}: Bearer ${KEY_PLACEHOLDER}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${MODEL_ALIAS}",
    "messages": [{ "role": "user", "content": "Hello!" }]
  }'`;

  // ── MCP gateway ────────────────────────────────────────────────────────────────
  // LiteLLM exposes an MCP gateway on the SAME host, under /mcp, authenticated with
  // the SAME `x-litellm-api-key` Bearer key. An optional `x-mcp-servers` header (or
  // a /mcp/<group> URL) scopes the exposed tools to named servers and/or groups.
  const mcpUrl = `${apiBase}/mcp`;
  const mcpConfig = `{
  "mcpServers": {
    "litellm": {
      "url": "${mcpUrl}",
      "headers": {
        "${AUTH_HEADER}": "Bearer ${KEY_PLACEHOLDER}"
      }
    }
  }
}`;
  const mcpFilteredConfig = `{
  "mcpServers": {
    "litellm": {
      "url": "${mcpUrl}",
      "headers": {
        "${AUTH_HEADER}": "Bearer ${KEY_PLACEHOLDER}",
        "x-mcp-servers": "Zapier_Gmail,dev-group"
      }
    }
  }
}`;

  // ── Editor / CLI setup ───────────────────────────────────────────────────────
  // Live setup for Claude Code, Gemini CLI, opencode, and codex. The base URL is
  // the user's live gateway (apiBase); the key is the `sk-...` placeholder (mint
  // it on Keys). `caption` overrides the code-box label (e.g. a config-file path);
  // `note` adds a one-line instruction; `guide` links the authoritative doc.
  const TOOLS: {
    id: string;
    label: string;
    ready: boolean;
    code: string;
    caption?: string;
    note?: string;
    guide?: { url: string; label: string };
  }[] = [
    {
      id: 'claude',
      label: 'Claude Code',
      ready: true,
      code: `# Claude Code → LiteLLM
export ANTHROPIC_BASE_URL="${apiBase}"
export ANTHROPIC_AUTH_TOKEN=${KEY_PLACEHOLDER}
export ANTHROPIC_MODEL="ackstorm.smart"
export ANTHROPIC_DEFAULT_OPUS_MODEL="ackstorm.smart"
export ANTHROPIC_DEFAULT_SONNET_MODEL="ackstorm.fast"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="ackstorm.fast-lite"
export CLAUDE_CODE_SUBAGENT_MODEL="ackstorm.fast"

claude`,
      guide: {
        url: 'https://docs.litellm.ai/docs/tutorials/claude_code_max_subscription',
        label: 'Claude Code + LiteLLM guide',
      },
    },
    {
      id: 'gemini',
      label: 'Gemini CLI',
      ready: true,
      code: `# Gemini CLI → LiteLLM
export GOOGLE_GEMINI_BASE_URL=${apiBase}/gemini
export GEMINI_BASE_URL=${apiBase}/gemini/v1beta
export GEMINI_API_KEY=${KEY_PLACEHOLDER}

gemini`,
    },
    {
      id: 'opencode',
      label: 'opencode',
      ready: true,
      caption: '~/.config/opencode/opencode.json',
      // opencode is configured by a JSON file (NOT env vars): an OpenAI-compatible
      // provider pointed at the gateway. The model keys MUST match LiteLLM aliases.
      code: `{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "litellm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LiteLLM",
      "options": {
        "baseURL": "${apiBase}/v1",
        "apiKey": "${KEY_PLACEHOLDER}"
      },
      "models": {
        "ackstorm.fast": { "name": "ACKstorm Fast" },
        "ackstorm.smart": { "name": "ACKstorm Smart" }
      }
    }
  }
}`,
      note: 'Save the file, then run `opencode` and pick a LiteLLM model with `/models`.',
      guide: {
        url: 'https://docs.litellm.ai/docs/tutorials/opencode_integration',
        label: 'opencode + LiteLLM guide',
      },
    },
    {
      id: 'codex',
      label: 'codex',
      ready: true,
      code: `# codex → LiteLLM (OpenAI-compatible)
export OPENAI_API_KEY="${KEY_PLACEHOLDER}"
export OPENAI_BASE_URL="${apiBase}/v1"

codex --model ${MODEL_ALIAS}`,
    },
    {
      id: 'copilot',
      label: 'GitHub Copilot',
      ready: true,
      caption: 'VS Code settings.json',
      // GitHub Copilot (VS Code) is pointed at the gateway by overriding its proxy
      // URL in settings.json; reload the window afterwards.
      code: `{
  "github.copilot.advanced": {
    "debug.overrideProxyUrl": "${apiBase}",
    "debug.testOverrideProxyUrl": "${apiBase}"
  }
}`,
      note: 'Reload VS Code after saving. Authenticate with your gateway key when prompted — see the guide for model + auth details.',
      guide: {
        url: 'https://docs.litellm.ai/docs/tutorials/github_copilot_integration',
        label: 'GitHub Copilot + LiteLLM guide',
      },
    },
    {
      id: 'qwen',
      label: 'Qwen Code',
      ready: true,
      code: `# Qwen Code CLI → LiteLLM (OpenAI-compatible)
export OPENAI_BASE_URL="${apiBase}/v1"
export OPENAI_API_KEY="${KEY_PLACEHOLDER}"
export OPENAI_MODEL="${MODEL_ALIAS}"

qwen`,
      guide: {
        url: 'https://docs.litellm.ai/docs/tutorials/litellm_qwen_code_cli',
        label: 'Qwen Code + LiteLLM guide',
      },
    },
  ];
  const [tool, setTool] = useState<string>('claude');
  const [mcpTab, setMcpTab] = useState<string>('access');

  return (
    <div className="flex flex-col gap-8">
      {/* Page header */}
      <div>
        <h1 className="font-sans text-2xl font-semibold leading-snug text-text-primary">
          How-to
        </h1>
        <p className="mt-1 font-sans text-sm text-text-secondary">
          You have a key — here is how to make your first call to{' '}
          <span className="font-mono text-text-primary">{brandShort}</span>,
          wire up your editor, or skip the terminal entirely.
        </p>
      </div>

      <div className="grid gap-10 lg:grid-cols-[180px_1fr]">
        {/* Sticky in-page TOC (desktop only). Buttons, not hash anchors — the
            hash belongs to the router. */}
        <aside className="hidden lg:block">
          <nav
            aria-label="On this page"
            className="sticky top-8 flex flex-col gap-1"
          >
            <div className="mb-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
              On this page
            </div>
            {TOC.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => scrollToSection(item.id)}
                className="cursor-pointer rounded-md px-2.5 py-1.5 text-left font-sans text-sm text-text-secondary transition-colors hover:bg-primary/5 hover:text-text-primary"
              >
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Content column */}
        <div className="flex min-w-0 flex-col gap-12">
          {/* §1 Quickstart */}
          <Section
            id="quickstart"
            icon={Terminal}
            title="Quickstart"
            sub="Two steps to your first response: mint a key, then call the gateway."
          >
            <div className="flex flex-col gap-5">
              {/* Step 1 — mint a key */}
              <div className="flex gap-3">
                <StepBadge n={1} />
                <div className="min-w-0 flex-1">
                  <div className="font-sans text-sm font-medium text-text-primary">
                    Mint a virtual key
                  </div>
                  <p className="mt-1 font-sans text-sm leading-relaxed text-text-secondary">
                    Create one on the{' '}
                    <button
                      type="button"
                      onClick={() => navigate('/')}
                      className="inline-flex cursor-pointer items-center gap-1 font-medium text-primary hover:underline"
                    >
                      <KeyRound className="size-3.5" aria-hidden="true" />
                      Keys
                    </button>{' '}
                    tab. The{' '}
                    <span className="font-mono text-text-primary">sk-</span> value
                    is shown <span className="text-text-primary">once</span>, at
                    creation — copy it then; it is never displayed again.
                  </p>
                </div>
              </div>

              {/* Step 2 — call the gateway */}
              <div className="flex gap-3">
                <StepBadge n={2} />
                <div className="min-w-0 flex-1">
                  <div className="font-sans text-sm font-medium text-text-primary">
                    Call the gateway
                  </div>
                  <p className="mt-1 mb-3 font-sans text-sm leading-relaxed text-text-secondary">
                    Swap{' '}
                    <span className="font-mono text-text-primary">
                      {KEY_PLACEHOLDER}
                    </span>{' '}
                    for your key and run it. The endpoint is OpenAI-compatible —{' '}
                    <span className="font-mono text-text-primary">
                      {MODEL_ALIAS}
                    </span>{' '}
                    is a standard model alias.
                  </p>
                  <CodeBlock code={curlSnippet} caption="curl" />
                </div>
              </div>
            </div>
          </Section>

          {/* §2 Editors & CLIs */}
          <Section
            id="tools"
            icon={ArrowRight}
            title="Editors & CLIs"
            sub="Point your AI coding tool at the gateway. Export the variables, then run the tool as usual."
          >
            <Tabs value={tool} onValueChange={setTool}>
              <TabsList variant="line">
                {TOOLS.map((t) => (
                  <TabsTrigger key={t.id} value={t.id}>
                    {t.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {TOOLS.map((t) => (
                <TabsContent key={t.id} value={t.id} className="mt-4">
                  <CodeBlock code={t.code} caption={t.caption ?? `${t.label} · setup`} />
                  {t.note && (
                    <p className="mt-2 font-sans text-xs leading-relaxed text-text-tertiary">
                      {t.note}
                    </p>
                  )}
                  {t.guide && (
                    <a
                      href={t.guide.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-2 inline-flex items-center gap-1 font-sans text-xs font-medium text-primary hover:underline"
                    >
                      {t.guide.label}
                      <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  )}
                  {!t.ready && (
                    <p className="mt-2 font-sans text-xs text-text-tertiary">
                      Placeholder — tested {t.label} values land here soon.
                    </p>
                  )}
                </TabsContent>
              ))}
            </Tabs>
            <p className="mt-3 font-sans text-xs leading-relaxed text-text-tertiary">
              Swap {KEY_PLACEHOLDER} for your key (mint it on the Keys tab). The
              base URL is your live gateway; only the key differs per user.
            </p>
          </Section>

          {/* §3 MCP servers */}
          <Section
            id="mcp"
            icon={Server}
            title="MCP servers"
            sub="Give MCP-capable clients (Cursor, Claude Desktop, …) access to the gateway's tool servers. The MCP endpoint lives on the same gateway host, under /mcp, and uses your same virtual key."
          >
            <Tabs value={mcpTab} onValueChange={setMcpTab}>
              <TabsList variant="line">
                <TabsTrigger value="access">MCP Access</TabsTrigger>
                <TabsTrigger value="group">MCP Group access</TabsTrigger>
              </TabsList>

              <TabsContent value="access" className="mt-4">
                <p className="mb-3 font-sans text-sm leading-relaxed text-text-secondary">
                  Every tool you can reach. URL{' '}
                  <span className="font-mono text-text-primary">{mcpUrl}</span>,
                  auth header{' '}
                  <span className="font-mono text-text-primary">
                    {AUTH_HEADER}
                  </span>{' '}
                  (the same Bearer key as chat).
                </p>
                <CodeBlock code={mcpConfig} caption="MCP client config" />
              </TabsContent>

              <TabsContent value="group" className="mt-4">
                <p className="mb-3 font-sans text-sm leading-relaxed text-text-secondary">
                  Scope to specific servers and/or groups with the{' '}
                  <span className="font-mono text-text-primary">
                    x-mcp-servers
                  </span>{' '}
                  header (comma-separated) — or target a group straight from the
                  URL,{' '}
                  <span className="font-mono text-text-primary">
                    {`${mcpUrl}/dev-group`}
                  </span>
                  .
                </p>
                <CodeBlock
                  code={mcpFilteredConfig}
                  caption="MCP client config · scoped"
                />
              </TabsContent>
            </Tabs>

            <a
              href="https://docs.litellm.ai/docs/mcp"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1 font-sans text-xs font-medium text-primary hover:underline"
            >
              LiteLLM MCP gateway guide
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          </Section>

          {/* §4 No terminal? */}
          <Section
            id="chat"
            icon={MessageSquare}
            title="No terminal?"
            sub="Prefer a chat window over a shell? Use a browser UI — paste your key once and start chatting."
          >
            <div className="grid gap-4 sm:grid-cols-2">
              {/* ACKstorm Chat — hosted */}
              <a
                href={chatUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 transition-colors hover:border-primary"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-sans text-sm font-semibold text-text-primary">
                    ACKstorm Chat
                  </span>
                  <ExternalLink
                    className="size-4 text-text-tertiary transition-colors group-hover:text-primary"
                    aria-hidden="true"
                  />
                </div>
                <p className="font-sans text-sm leading-relaxed text-text-secondary">
                  Hosted chat UI, ready to use — sign in and pick{' '}
                  <span className="font-mono text-text-primary">
                    {MODEL_ALIAS}
                  </span>
                  . Nothing to install.
                </p>
                <span className="mt-1 break-all font-mono text-[11px] text-text-tertiary">
                  {chatUrl}
                </span>
              </a>

              {/* openwork — coming soon (not yet wired to the gateway) */}
              <a
                href="https://github.com/different-ai/openwork"
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col gap-2 rounded-xl border border-border bg-surface p-5 transition-colors hover:border-primary"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <span className="font-sans text-sm font-semibold text-text-primary">
                      openwork
                    </span>
                    <span className="inline-flex items-center rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                      Sooner
                    </span>
                  </span>
                  <ExternalLink
                    className="size-4 text-text-tertiary transition-colors group-hover:text-primary"
                    aria-hidden="true"
                  />
                </div>
                <p className="font-sans text-sm leading-relaxed text-text-secondary">
                  Open-source AI workspace. Gateway support is on the way — not
                  available yet. Star the repo to follow along.
                </p>
                <span className="mt-1 break-all font-mono text-[11px] text-text-tertiary">
                  github.com/different-ai/openwork
                </span>
              </a>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
