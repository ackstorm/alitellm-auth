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

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/deps /usr/local/lib/python3.12/site-packages
COPY --from=builder /app/deps/bin /usr/local/bin
COPY src/api/app ./app

EXPOSE 8080

# non-root: uid 10001 (numeric USER so kubelet runAsNonRoot can verify without /etc/passwd)
RUN useradd -u 10001 -m appuser
USER 10001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
