# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm

FROM ${PYTHON_IMAGE} AS library-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY time-atlas-python/ ./time-atlas-python/

RUN python -m pip wheel --no-deps --wheel-dir /wheels ./time-atlas-python

FROM ${PYTHON_IMAGE}

ARG USER_ID=1000
ARG GROUP_ID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/workspace"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && if ! getent group "${GROUP_ID}" >/dev/null; then groupadd --gid "${GROUP_ID}" atlas; fi \
    && useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash atlas \
    && python -m venv "${VIRTUAL_ENV}" \
    && mkdir -p /workspace /home/atlas/.cache \
    && chown -R "${USER_ID}:${GROUP_ID}" "${VIRTUAL_ENV}" /workspace /home/atlas

WORKDIR /workspace

# Install third-party dependencies before copying the rest of the repository so
# this layer remains cached while data-production code and source data change.
COPY --chown=${USER_ID}:${GROUP_ID} requirements.lock ./requirements.lock

USER atlas

RUN python -m pip install --require-hashes --requirement requirements.lock

# The library's runtime dependencies are already pinned in requirements.lock.
RUN --mount=type=bind,from=library-builder,source=/wheels,target=/wheels \
    python -m pip install --no-deps --no-index /wheels/time_atlas_python-*.whl

COPY --chown=${USER_ID}:${GROUP_ID} --exclude=time-atlas-python . .

# The image contains the main repository working tree only. Git metadata and
# submodule working trees are excluded by .dockerignore or by COPY --exclude.
# The probe below mirrors what the modeling agent checks at the start of every run.
RUN test ! -e .git \
    && test ! -e data-lausanne \
    && test ! -e data-venice \
    && test ! -e time-atlas-python \
    && python - <<'PY'
from importlib.metadata import version
from pathlib import Path

import geopandas, rasterio, timeatlas
from timeatlas import RDECollection

files = [
    "AGENTS.md",
    ".github/skills/timeatlas-pre-production-analysis/SKILL.md",
    ".github/skills/timeatlas-output-file-format/SKILL.md",
]
methods = [
    "aggregate_observations_into_points_of_interest",
    "produce_area_from_current_extent",
    "save_rde_to_files",
    "validate_data",
]

empty = [name for name in files if not Path("/workspace", name).read_text(encoding="utf-8").strip()]
missing = [name for name in methods if not callable(getattr(RDECollection, name, None))]
if empty:
    raise SystemExit(f"Empty instruction files: {', '.join(empty)}")
if missing:
    raise SystemExit(f"RDECollection is missing: {', '.join(missing)}")
print("time-atlas-python", version("time-atlas-python"))
PY

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
