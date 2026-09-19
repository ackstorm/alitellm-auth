#!/usr/bin/env node
// Reference Den control plane: the OpenWork contract, verified against the real desktop.
// Implements the minimum contract from ee/apps/den-api/src/routes/auth/desktop-handoff.ts
//   node den.mjs           # listens on http://localhost:8787
//   PORT=9000 node den.mjs
// Point OpenWork at it: Settings > Advanced > Organization server URL.

import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";

const PORT = Number(process.env.PORT ?? 8787);
const ORIGIN = process.env.DEN_ORIGIN ?? `http://localhost:${PORT}`;
const API_BASE = `${ORIGIN}/api/den`;
const EMAIL = process.env.DEN_EMAIL ?? "dev@localhost";
const GRANT_TTL_MS = 5 * 60 * 1000;

const USER = { id: "user_refdev00000000000000000", email: EMAIL, name: "Reference Dev" };
const ORG = { id: "organization_alitellm0000000", slug: "alitellm-auth", name: "AliteLLM Auth" };

// --- Org branding + policy --------------------------------------------------
// Served from GET /v1/me/desktop-config. The local OpenWork server fetches and
// persists this, then denies actions with 403 organization_policy_denied, so
// these limits are not a UI preference the user can switch off.
// Schema: packages/types/src/den/desktop-policies.ts:330
const BRAND_DIR = new URL("./brand/", import.meta.url);
const DESKTOP_CONFIG = {
  // Branding. brandAccentColor must be one of the 22 Radix families listed at
  // desktop-policies.ts:302 — "mint" is the softest pastel of them.
  brandAppName: "AliteLLM Auth",
  brandLogoUrl: `${ORIGIN}/brand/logo.svg`,
  brandIconUrl: `${ORIGIN}/brand/icon.svg`,
  brandAccentColor: "mint",

  // Capability policy. Left permissive on purpose: allowCustomProviders false
  // would hide the provider that comes from OpenCode's own config,
  // and allowManageExtensions false would block adding the auth plugin.
  allowCustomProviders: true,
  allowManageExtensions: true,
  allowControlSettings: true,
  allowBuiltInExtensions: true,
  allowMultipleWorkspaces: true,
  allowZenModel: true,
  allowAlphaUpdates: false,
  showWelcomePage: false,

  // Execution limits — the part a user cannot undo locally.
  // Patterns are case-insensitive globs (* and ?) matched against the whole
  // command string (managed-policy-rules.ts:58).
  // NOTE: a non-empty blockedCommands list also disables interactive terminals
  // and saved commands outright (managed-policy-rules.ts:77-78).
  execution: {
    commands: "allow",
    blockedCommands: [
      "rm -rf /*",
      "* | sh",
      "* | bash",
      "curl * -o /etc/*",
      "shutdown*",
      "mkfs*",
    ],
    blockBrowserUploads: false,
  },

  automationsEnabled: true,
  dashboardEnabled: true,
  connectEnabled: false,
};

// Empty-but-valid payloads for an org with nothing configured. Key names come
// from the parsers in apps/app/src/app/lib/den.ts (getDenOrgLlmProviders,
// getOrgMarketplaces, getMeLibraryPlugins, normalizeDenResourceSnapshot, ...).
const EMPTY_GET = {
  "/api/den/v1/llm-providers": { llmProviders: [] },
  "/api/den/v1/inference-providers": { inferenceProviders: [] },
  "/api/den/v1/inference/analytics/settings": {
    available: false,
    subscribed: false,
    modelsEnabled: false,
    enabled: false,
    consentedAt: null,
    consentVersion: null,
    exportEnabled: false,
    langfuseHost: null,
    langfuseConfigured: false,
  },
  "/api/den/v1/marketplaces": { items: [] },
  "/api/den/v1/resources/marketplace-capabilities": { items: [] },
  "/api/den/v1/me/library": { items: [] },
  "/api/den/v1/me/dashboards": { items: [] },
  "/api/den/v1/mcp-connections": { connections: [] },
  "/api/den/v1/mcp-connections/presets": { presets: [] },
  "/api/den/v1/apps": { enabled: false, sharingEnabled: false, items: [] },
  "/api/den/v1/automations": { items: [], nextCursor: null },
  "/api/den/v1/cloud-automations": { items: [], nextCursor: null },
  "/api/den/v1/plugins": { items: [] },
  "/api/den/v1/resources": {
    organizationId: ORG.id,
    orgMemberId: "orgmember_refdev000000000000",
    teamIds: [],
    resources: { llmProviders: {}, marketplaces: [] },
  },
};

/** grant -> { expiresAt, consumed } */
const grants = new Map();
/** issued session tokens, persisted so restarts keep the desktop signed in */
const TOKEN_FILE = new URL("./den-tokens.json", import.meta.url);
const tokens = new Set(
  existsSync(TOKEN_FILE) ? JSON.parse(readFileSync(TOKEN_FILE, "utf8")) : [],
);

function persistTokens() {
  writeFileSync(TOKEN_FILE, JSON.stringify([...tokens]));
}

function mintGrant() {
  const grant = randomBytes(24).toString("base64url");
  grants.set(grant, { expiresAt: Date.now() + GRANT_TTL_MS, consumed: false });
  return grant;
}

function deepLink(grant) {
  const url = new URL("openwork://den-auth");
  url.searchParams.set("grant", grant);
  url.searchParams.set("denBaseUrl", API_BASE);
  return url.toString();
}

function cors(req, res) {
  // credentials: "include" on the client means the origin must be reflected,
  // never "*", or the browser/runtime drops the response.
  res.setHeader("Access-Control-Allow-Origin", req.headers.origin ?? "*");
  res.setHeader("Access-Control-Allow-Credentials", "true");
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "authorization,content-type,accept,x-organization-id,x-openwork-organization-id",
  );
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(payload);
  return status;
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function bearer(req) {
  const header = req.headers.authorization ?? "";
  return header.toLowerCase().startsWith("bearer ") ? header.slice(7).trim() : "";
}

function requireToken(req, res) {
  const token = bearer(req);
  if (!token || !tokens.has(token)) {
    json(res, 401, { error: "unauthorized", message: "Missing or unknown session token." });
    return null;
  }
  return token;
}

// --- Org skill catalog ------------------------------------------------------
// Every .md file in ./skills is published to the desktop as a native OpenCode
// skill. The engine reads skill://index.json, then one skill://<name>/SKILL.md
// per entry (apps/server/src/cloud-native-skills.ts:82 defines both shapes).
// Read fresh per request so editing a file needs no restart.
const SKILL_DIR = new URL("./skills/", import.meta.url);

function listSkills() {
  if (!existsSync(SKILL_DIR)) return [];
  return readdirSync(SKILL_DIR)
    .filter((file) => file.endsWith(".md"))
    .map((file) => file.slice(0, -3))
    .sort()
    .map((name) => ({ name, type: "skill-md", url: `skill://${name}/SKILL.md` }));
}

function readSkillBody(uri) {
  const match = /^skill:\/\/([^/]+)\/SKILL\.md$/.exec(uri);
  const name = match?.[1];
  // Reject traversal: the name must match a file this directory actually lists.
  if (!name || !listSkills().some((skill) => skill.name === name)) return null;
  return readFileSync(new URL(`${name}.md`, SKILL_DIR), "utf8");
}

/** MCP resources this stub publishes, keyed by URI. Returns text or null. */
function readMcpResource(uri) {
  if (uri === "skill://index.json") {
    return JSON.stringify({ skills: listSkills() }, null, 2);
  }
  if (uri === "automation://index.json") {
    return JSON.stringify({ fetchedAt: Date.now(), total: 0, omitted: 0, automations: [] });
  }
  return readSkillBody(uri);
}

// --- Cloud MCP stub -------------------------------------------------------
// OpenWork mints a token here, then the local engine registers `${resource}/agent`
// as a remote MCP server and probes it. Health only turns green when the two
// tools in OPENWORK_CLOUD_EXPECTED_TOOLS (apps/server/src/cloud-mcp-health.ts:24)
// show up, so this speaks just enough Streamable HTTP MCP to expose them.
const MCP_RESOURCE = `${ORIGIN}/api/den/mcp`;
const MCP_TOOLS = [
  {
    name: "search_capabilities",
    description: "Stub capability search. Always returns an empty result set.",
    inputSchema: {
      type: "object",
      properties: { query: { type: "string", description: "What to search for." } },
      required: ["query"],
    },
  },
  {
    name: "execute_capability",
    description: "Stub capability execution. Never actually runs anything.",
    inputSchema: {
      type: "object",
      properties: {
        capabilityId: { type: "string" },
        input: { type: "object", additionalProperties: true },
      },
      required: ["capabilityId"],
    },
  },
];
/** MCP access tokens, kept apart from Den session tokens and persisted too:
 *  a restart that invalidated them would 401 the engine until it re-minted. */
const MCP_TOKEN_FILE = new URL("./den-mcp-tokens.json", import.meta.url);
const mcpTokens = new Set(
  existsSync(MCP_TOKEN_FILE) ? JSON.parse(readFileSync(MCP_TOKEN_FILE, "utf8")) : [],
);

function persistMcpTokens() {
  writeFileSync(MCP_TOKEN_FILE, JSON.stringify([...mcpTokens]));
}

function mcpResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function mcpError(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

/** Returns a JSON-RPC response, or null for notifications (no reply). */
function handleMcpMessage(message) {
  if (!message || message.jsonrpc !== "2.0" || typeof message.method !== "string") {
    return mcpError(message?.id ?? null, -32600, "Invalid request");
  }
  const { id, method, params } = message;
  if (id === undefined) return null; // notification

  switch (method) {
    case "initialize":
      return mcpResult(id, {
        protocolVersion: typeof params?.protocolVersion === "string" ? params.protocolVersion : "2025-06-18",
        capabilities: { tools: { listChanged: false }, resources: { listChanged: false } },
        serverInfo: { name: "openwork-den-reference", version: "0.1.0" },
      });
    case "ping":
      return mcpResult(id, {});
    case "tools/list":
      return mcpResult(id, { tools: MCP_TOOLS, nextCursor: undefined });
    case "tools/call": {
      const name = params?.name;
      if (!MCP_TOOLS.some((tool) => tool.name === name)) {
        return mcpError(id, -32602, `Unknown tool: ${name}`);
      }
      return mcpResult(id, {
        content: [{ type: "text", text: `den: ${name} is a stub, nothing was executed.` }],
        isError: false,
      });
    }
    case "resources/list":
      return mcpResult(id, {
        resources: [
          { uri: "skill://index.json", name: "Skill index", mimeType: "application/json" },
          { uri: "automation://index.json", name: "Automation index", mimeType: "application/json" },
          ...listSkills().map((skill) => ({
            uri: skill.url,
            name: skill.name,
            mimeType: "text/markdown",
          })),
        ],
      });
    case "resources/read": {
      const uri = params?.uri ?? "";
      const text = readMcpResource(uri);
      console.log(`  mcp -> resources/read uri=${uri} -> ${text === null ? "NOT FOUND" : `${text.length}b`}`);
      if (text === null) return mcpError(id, -32002, `Resource not found: ${uri}`);
      // The reader matches on uri, so it has to come back verbatim.
      return mcpResult(id, {
        contents: [{
          uri,
          mimeType: uri.endsWith(".json") ? "application/json" : "text/markdown",
          text,
        }],
      });
    }
    case "prompts/list":
      return mcpResult(id, { prompts: [] });
    default:
      return mcpError(id, -32601, `Method not found: ${method}`);
  }
}

function signInPage(mode, grant) {
  const link = deepLink(grant);
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Reference Den - ${mode}</title>
<style>
 body{font:15px/1.5 system-ui,sans-serif;max-width:46rem;margin:3rem auto;padding:0 1rem;color:#222}
 code,input{font-family:ui-monospace,monospace;font-size:13px}
 input{width:100%;padding:.6rem;box-sizing:border-box}
 button{padding:.6rem 1rem;font-size:15px;cursor:pointer}
 .box{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}
 .ok{color:#137333}
</style></head><body>
<h1>Reference Den</h1>
<p>Mode: <code>${mode}</code> - grant minted, valid 5 minutes, single use.</p>
<div class="box">
  <p><strong>1.</strong> Try the deep link (works only if <code>openwork://</code> is registered with your desktop):</p>
  <p><button id="open">Open in OpenWork</button></p>
  <p><strong>2.</strong> Or copy this and paste it into OpenWork: account menu &rarr; "Paste sign-in code".</p>
  <input id="link" readonly value="${link}">
  <p><button id="copy">Copy link</button> <span id="copied" class="ok"></span></p>
</div>
<p>Raw grant: <code>${grant}</code></p>
<script>
 document.getElementById("open").onclick = () => { location.href = document.getElementById("link").value; };
 document.getElementById("copy").onclick = async () => {
   const field = document.getElementById("link");
   field.select();
   try { await navigator.clipboard.writeText(field.value); } catch { document.execCommand("copy"); }
   document.getElementById("copied").textContent = "copied";
 };
</script>
</body></html>`;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", ORIGIN);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  cors(req, res);

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    console.log(`  204 OPTIONS ${path}`);
    return;
  }

  let status;

  if (req.method === "GET" && path === "/") {
    const grant = mintGrant();
    const body = signInPage(url.searchParams.get("mode") ?? "sign-in", grant);
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(body);
    status = 200;
  } else if (req.method === "GET" && path === "/api/runtime-config") {
    status = json(res, 200, { denApiUrl: API_BASE });
  } else if (req.method === "POST" && path === "/api/den/v1/auth/desktop-handoff/exchange") {
    const body = await readBody(req);
    const grant = typeof body?.grant === "string" ? body.grant.trim() : "";
    const entry = grants.get(grant);
    if (!entry || entry.consumed || entry.expiresAt <= Date.now()) {
      status = json(res, 404, {
        error: "grant_not_found",
        message: "This desktop sign-in link is missing, expired, or already used.",
      });
    } else {
      entry.consumed = true;
      const token = randomBytes(32).toString("base64url");
      tokens.add(token);
      persistTokens();
      status = json(res, 200, { token, user: USER, organization: ORG, connectEnabled: false });
    }
  } else if (req.method === "POST" && path === "/api/den/v1/auth/desktop-handoff/status") {
    const body = await readBody(req);
    const entry = grants.get(typeof body?.grant === "string" ? body.grant.trim() : "");
    const state = !entry || entry.expiresAt <= Date.now() ? "unknown" : entry.consumed ? "consumed" : "pending";
    status = json(res, 200, { status: state });
  } else if (req.method === "GET" && path === "/api/den/v1/me") {
    status = requireToken(req, res) ? json(res, 200, { user: USER }) : 401;
  } else if (req.method === "GET" && path === "/api/den/v1/me/orgs") {
    status = requireToken(req, res)
      ? json(res, 200, {
          orgs: [{ ...ORG, role: "owner" }],
          activeOrgId: ORG.id,
          activeOrgSlug: ORG.slug,
        })
      : 401;
  } else if (req.method === "POST" && path === "/api/den/v1/me/active-organization") {
    status = requireToken(req, res) ? json(res, 200, { activeOrgId: ORG.id, activeOrgSlug: ORG.slug }) : 401;
  } else if (req.method === "POST" && path === "/api/den/api/auth/sign-out") {
    tokens.delete(bearer(req));
    persistTokens();
    status = json(res, 200, {});
  } else if (req.method === "GET" && path.startsWith("/brand/")) {
    const name = path.slice("/brand/".length);
    // Only the two published marks; never an arbitrary path.
    if (name !== "logo.svg" && name !== "icon.svg") {
      status = json(res, 404, { error: "not_found", message: `No brand asset ${name}` });
    } else {
      res.writeHead(200, { "Content-Type": "image/svg+xml", "Cache-Control": "no-cache" });
      res.end(readFileSync(new URL(name, BRAND_DIR)));
      status = 200;
    }
  } else if (req.method === "GET" && path === "/api/den/v1/me/desktop-config") {
    status = requireToken(req, res) ? json(res, 200, DESKTOP_CONFIG) : 401;
  } else if (req.method === "POST" && path === "/api/den/v1/telemetry/ingest") {
    status = json(res, 200, {});
  } else if (req.method === "POST" && path === "/api/den/v1/mcp/token") {
    if (!requireToken(req, res)) {
      status = 401;
    } else {
      const mcpToken = randomBytes(32).toString("base64url");
      mcpTokens.add(mcpToken);
      persistMcpTokens();
      status = json(res, 200, {
        token: mcpToken,
        expiresAt: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
        organizationId: ORG.id,
        scopes: ["mcp:read", "mcp:write"],
        resource: MCP_RESOURCE,
      });
    }
  } else if (path === "/api/den/mcp/agent") {
    if (!mcpTokens.has(bearer(req))) {
      status = json(res, 401, { error: "unauthorized", message: "Missing or unknown MCP token." });
    } else if (req.method === "POST") {
      const body = await readBody(req);
      const messages = Array.isArray(body) ? body : [body];
      console.log(`  mcp -> ${messages.map((m) => m?.method ?? "?").join(", ")}`);
      const replies = messages.map(handleMcpMessage).filter(Boolean);
      for (const reply of replies) {
        if (reply.error) console.log(`  mcp <- ERROR ${reply.error.code} ${reply.error.message}`);
      }
      if (replies.length === 0) {
        res.writeHead(202);
        res.end();
        status = 202;
      } else {
        status = json(res, 200, Array.isArray(body) ? replies : replies[0]);
      }
    } else if (req.method === "DELETE") {
      // Session teardown: nothing is kept per session.
      res.writeHead(204);
      res.end();
      status = 204;
    } else if (req.method === "GET") {
      // Notification channel. This stub never pushes anything, so the stream
      // stays open with only keep-alive comments until the client leaves.
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      res.write(": connected\n\n");
      const keepAlive = setInterval(() => res.write(": ping\n\n"), 15_000);
      req.on("close", () => clearInterval(keepAlive));
      status = 200;
      console.log(`  200 GET ${path} (sse stream open)`);
      return;
    } else {
      res.writeHead(405, { Allow: "GET, POST, DELETE" });
      res.end();
      status = 405;
    }
  } else if (req.method === "GET" && Object.hasOwn(EMPTY_GET, path)) {
    status = requireToken(req, res) ? json(res, 200, EMPTY_GET[path]) : 401;
  } else if (path === "/favicon.ico") {
    res.writeHead(204);
    res.end();
    status = 204;
  } else {
    // Everything else: log loudly so we learn the endpoint surface the app wants.
    status = json(res, 404, { error: "not_implemented", message: `No handler for ${req.method} ${path}` });
  }

  console.log(`  ${status} ${req.method} ${path}`);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`den listening on ${ORIGIN}`);
  console.log(`  set OpenWork's Organization server URL to: ${ORIGIN}`);
});
