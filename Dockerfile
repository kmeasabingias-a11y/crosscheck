# CrossCheck API image.
#
# Two stages: a builder that resolves and installs the virtualenv, and a runtime that carries
# only the finished venv. The build tooling (uv, the uv cache, the wheel build) never reaches
# the shipped image.
#
# The image deliberately does NOT contain the models. bge-large, bge-reranker-v2-m3 and
# nli-deberta-v3-base come to 4.2 GB — nearly twice the size of this entire image (2.27 GB) —
# and baking them in would put that payload in a layer that has to be rebuilt on every machine
# and re-pulled after any change to the layers beneath it. They live in a named volume instead,
# filled once by the `warm-models` service in docker-compose.yml, which the API waits on before
# accepting traffic. The volume then survives image rebuilds entirely. See DECISIONS.md D48.

# ---------------------------------------------------------------------------
# Stage 1 — builder: resolve and install the virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# Pinned to the uv that produced uv.lock, so the image resolves the lock the same way the
# developer machine does rather than tracking whatever :latest happens to be that week.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, WITHOUT the project. This layer is keyed on pyproject.toml and uv.lock
# alone, so editing source code does not re-resolve or re-download roughly 1.3 GB of wheels —
# torch dominates that, and it is the difference between a 20-second rebuild and a 10-minute one.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable --extra ui

# Then the project itself, which is small and changes constantly. README.md is copied here
# rather than with the lockfile because pyproject's `readme` field makes the wheel build read
# it — and the README changes far more often than the dependencies do.
COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra ui

# ---------------------------------------------------------------------------
# Stage 2 — runtime.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# Non-root. The service parses uploaded documents from anonymous callers (there is no auth on
# the demo, by design — spec §3), so the process that touches them holds no privileges it does
# not need. The uid is pinned to 1000 rather than auto-assigned, which is what makes the named
# volume's ownership predictable across rebuilds. Not `--system`, which would reserve a uid
# below SYS_UID_MAX (999) and warn about the explicit 1000 overriding it.
RUN groupadd --gid 1000 crosscheck \
    && useradd --uid 1000 --gid crosscheck --create-home crosscheck

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Both model caches point into /models, the one mount the warm-up fills and the API reads.
# FASTEMBED_CACHE_PATH matters more than it looks: fastembed defaults to a directory under the
# system temp dir, so without this the BM25 model is re-downloaded on every container start
# while the three torch models are correctly cached.
ENV HF_HOME=/models/hf \
    FASTEMBED_CACHE_PATH=/models/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1

# Force the classic HTTPS download path instead of the hub's Xet content-addressed transfer.
# This is not a preference — Xet deadlocks here. Its adaptive concurrency controller reads the
# early small-file successes as headroom and climbs to ~49 parallel connections ("success ratio
# 1.000 ... increased concurrency from 48 to 49"), at which point the transfer wedges: the first
# cold `docker compose up` stopped dead at 64 MB and moved zero bytes in the following three
# minutes. Measured against the identical image and volume with only this variable changed, the
# classic path pulls the same models at ~13 MB/s. Suspected interaction with WSL2's NAT and that
# many concurrent sockets; either way, a reproducible stall on the very first run is not a
# trade-off worth making for a faster transfer that sometimes works.
ENV HF_HUB_DISABLE_XET=1

# Container-appropriate default; compose sets it too, and an operator running this image by hand
# against a Qdrant elsewhere overrides it. The bare `docker run` default of localhost:6333 would
# resolve to the container itself, which never has Qdrant in it.
ENV CROSSCHECK_QDRANT_URL=http://qdrant:6333

WORKDIR /app

# --no-editable above means the package (including the prompt .md files, which load through
# importlib.resources) is installed into site-packages proper, so the source tree is not part
# of the runtime image — only the venv is.
COPY --from=builder --chown=crosscheck:crosscheck /app/.venv /app/.venv

# The demo page and the reports it falls back to. Streamlit runs a script by path rather than an
# installed entry point, so unlike the package these are copied in as files. `--extra ui` above is
# what puts Streamlit in the venv; it adds ~100 MB to a 2.27 GB image, which is not worth a second
# image to avoid.
COPY --chown=crosscheck:crosscheck ui/ /app/ui/
COPY --chown=crosscheck:crosscheck benchmarks/ /app/benchmarks/

# The two writable paths. /models is the mountpoint for the model-cache volume; creating and
# chowning it in the image is what gives the volume the right ownership when Docker initialises
# it from the mountpoint. /app/.crosscheck holds uploads plus the claim and verdict caches that
# make a re-audit of the same corpus cheap.
RUN mkdir -p /models /app/.crosscheck \
    && chown -R crosscheck:crosscheck /models /app/.crosscheck

USER crosscheck

EXPOSE 8000

# Python rather than curl: the slim base has no HTTP client, and adding one for a health probe
# is a package (and a CVE surface) bought for four lines of stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "crosscheck.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
