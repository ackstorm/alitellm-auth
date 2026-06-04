# SPDX-License-Identifier: Apache-2.0
# Dev image for the alitellm-auth FastAPI service (DEV TOOLING ONLY).
#
# Installs the package's runtime deps from pyproject.toml so `uvicorn app.main:app
# --reload` works. The app/ source is BIND-MOUNTED at runtime (compose) so edits on
# the host hot-reload — nothing under app/ is baked in. Do NOT bake the UI: the
# browser gets the SPA from the `ui` (vite) service; the /ui StaticFiles mount in
# main.py uses check_dir=False so a missing dist is fine.
FROM python:3.12-slim

WORKDIR /src

# Install deps from pyproject. We copy only the metadata + an empty package so the
# editable install resolves; the real app/ is bind-mounted over /src/app at runtime.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --no-cache-dir -e .

EXPOSE 8080

# --reload watches /src/app (bind-mounted). --host 0.0.0.0 so the published port works.
CMD ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8080", "--reload-dir", "/src/app"]
