# ── Builder stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app

RUN pip install --no-cache-dir uv

# hatchling needs the package present to install; copy only what's required.
# No COPY . . — explicit paths only (per CLAUDE.md Docker rules).
COPY src/api/pyproject.toml ./pyproject.toml
COPY src/api/app ./app

RUN uv pip install --system --no-cache-dir --target=/app/deps .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# PYTHONPATH points at the install target so deps are version-agnostic:
# a python base bump (e.g. 3.12 -> 3.14) needs no path edit here.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/deps

COPY --from=builder /app/deps /app/deps
COPY src/api/app ./app

EXPOSE 8080

# non-root: uid 10001 (numeric USER so kubelet runAsNonRoot can verify without /etc/passwd)
RUN useradd -u 10001 -m appuser
USER 10001

# invoke via `python -m` so we don't depend on console-script shebangs or PATH
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
