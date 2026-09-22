FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv \
    # Fixed shared path rather than the default `~/.cache/ms-playwright`:
    # prod-with-browser installs the browser as root but runs as `appuser`,
    # which would otherwise have no access to root's home directory. Set here
    # (not in a later stage) since ENV placed between two FROM blocks attaches
    # to whichever stage precedes it, not the one that follows.
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    # Baked into the image rather than set at runtime via `os.environ` from
    # Python: Playwright's Node.js driver is a separate subprocess, and a
    # live env mutation in the Python process isn't reliably visible to a
    # browser process it spawns later. A fixed, always-present DISPLAY sidesteps
    # that entirely. Harmless on targets that never launch Xvfb (dev/prod).
    DISPLAY=:99

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# ── dev: editable-ish install with dev extras, source mounted as a volume ─────
FROM base AS dev
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir ".[dev]"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── prod: no dev deps, source baked in, non-root ──────────────────────────────
FROM base AS prod
RUN pip install --no-cache-dir .
COPY . .
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ── dev-with-browser: `dev` + Playwright/Chromium/Xvfb ─────────────────────────
# Only the `api` service needs this — remote-browser login sessions
# (api/app/linkedin/remote_browser/) run in-process there. `worker`/`beat`
# never launch a browser, so they stay on the plain `dev`/`prod` targets above
# rather than carrying Chromium's several-hundred-MB footprint for nothing.
# Xvfb itself is started lazily on first use (see remote_browser/xvfb.py), not
# here, so an idle api container doesn't pay for a running X server either.
FROM base AS dev-with-browser
RUN pip install --no-cache-dir -e ".[dev,browser]" || pip install --no-cache-dir ".[dev,browser]"
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── prod-with-browser: same idea, prod deps + non-root ──────────────────────────
FROM base AS prod-with-browser
RUN pip install --no-cache-dir ".[browser]"
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install --with-deps chromium
COPY . .
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /srv /ms-playwright
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
