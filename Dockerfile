# ── UI builder stage ───────────────────────────────────────────────────────────
# Node lives ONLY here; the stage is discarded so node never lands in runtime.
# Aligned with Dockerfile.devtools (NodeSource Node 22 LTS).
FROM node:22-slim AS ui-builder
WORKDIR /src/ui
# Explicit COPY paths only — NEVER `COPY . .` (CLAUDE.md). Copy the lockfile pair
# first so `npm ci` caches independently of source edits; the lockfile is exact
# (T-09-09: npm ci fails on lockfile drift, no floating npm install).
COPY src/ui/package.json src/ui/package-lock.json ./
RUN npm ci
# Copy the SPA source AFTER npm ci so a stale host node_modules/dist is irrelevant
# (npm ci regenerated deps from the lockfile). Explicit src/ui/ path — not `COPY . .`.
COPY src/ui/ ./
RUN npm run build      # emits /src/ui/dist (base: /ui/, hash-router shell)

# ── Builder stage ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder
WORKDIR /app

# uv as a prebuilt static binary from the official image. `pip install uv` is
# fragile on python:3.14-slim: when uv has no cp314 wheel yet, pip falls back to
# the sdist and tries to compile it with cargo, which fails on the slim image
# (no C toolchain → "linker `cc` not found"). The static binary sidesteps both.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

# hatchling needs the package present to install; copy only what's required.
# No COPY . . — explicit paths only (per CLAUDE.md Docker rules).
COPY src/api/pyproject.toml ./pyproject.toml
COPY src/api/app ./app

RUN uv pip install --system --no-cache-dir --target=/app/deps .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.14-slim
WORKDIR /app

# PYTHONPATH points at the install target so deps are version-agnostic:
# a python base bump (e.g. 3.12 -> 3.14) needs no path edit here.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/deps

COPY --from=builder /app/deps /app/deps
COPY src/api/app ./app

# Bake the built SPA in from the discarded ui-builder stage (D-01): `docker build`
# alone produces a serving image — no host `make build-ui` precondition. Placed
# before the USER switch so root owns the copy; FastAPI serves it at /ui.
COPY --from=ui-builder /src/ui/dist /app/ui/dist

EXPOSE 8080

# non-root: uid 10001 (numeric USER so kubelet runAsNonRoot can verify without /etc/passwd)
RUN useradd -u 10001 -m appuser
USER 10001

# invoke via `python -m` so we don't depend on console-script shebangs or PATH
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
