# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

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
COPY --chown=${USER_ID}:${GROUP_ID} requirements.txt ./requirements.txt
COPY --chown=${USER_ID}:${GROUP_ID} validation/requirements.txt ./validation/requirements.txt

USER atlas

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install \
        --requirement requirements.txt \
        --requirement validation/requirements.txt \
    && python -m pip install \
        --index-url https://test.pypi.org/simple/ \
        --no-deps \
        time-atlas-python==0.2.0

COPY --chown=${USER_ID}:${GROUP_ID} . .

# The image contains the main repository working tree only. Git metadata and
# submodule working trees are excluded by .dockerignore.
RUN test ! -e .git \
    && test ! -e data-lausanne \
    && test ! -e data-venice \
    && test ! -e time-atlas-python \
    && python -c "import geopandas, rasterio, timeatlas"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
