# syntax=docker/dockerfile:1.7
FROM node:24.11.1-bookworm-slim@sha256:48abc13a19400ca3985071e287bd405a1d99306770eb81d61202fb6b65cf0b57 AS assets

WORKDIR /build
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --ignore-scripts

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS python-base

FROM python-base AS python-build

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH} \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv "${VIRTUAL_ENV}"
COPY requirements-production.txt setup.py ./
COPY racetime ./racetime
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-production.txt \
    && pip install --no-compile --no-deps .

FROM python-base AS runtime-base

ARG VCS_REF=uncommitted
LABEL org.opencontainers.image.title="Z1RR Raceroom" \
      org.opencontainers.image.source="https://github.com/Z1Rracing/racetime-app" \
      org.opencontainers.image.licenses="GPL-3.0-only"
LABEL org.opencontainers.image.revision="${VCS_REF}"

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=project.settings.production \
    RACETIME_BUILD_COMMIT=${VCS_REF}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 racetime \
    && useradd --uid 10001 --gid 10001 --home-dir /srv/racetime \
        --shell /usr/sbin/nologin racetime \
    && install -d -o 10001 -g 10001 \
        /srv/racetime /srv/racetime/static /srv/racetime/media \
        /srv/racetime/announcer

WORKDIR /srv/racetime
COPY --from=python-build /opt/venv /opt/venv
COPY --from=assets --chown=10001:10001 /build/node_modules ./node_modules
COPY --chown=10001:10001 manage.py setup.py LICENSE ./
COPY --chown=10001:10001 project ./project
COPY --chown=10001:10001 racetime ./racetime
COPY --chown=10001:10001 .docker/start-production .docker/healthcheck ./.docker/
RUN chmod 0555 .docker/start-production .docker/healthcheck

USER 10001:10001

FROM runtime-base AS web
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["/srv/racetime/.docker/healthcheck", "web"]
ENTRYPOINT ["/srv/racetime/.docker/start-production"]
CMD ["web"]

FROM runtime-base AS racebot
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["/srv/racetime/.docker/healthcheck", "racebot"]
ENTRYPOINT ["/srv/racetime/.docker/start-production"]
CMD ["racebot"]

FROM runtime-base AS maintenance
USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends age zstd mariadb-client \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/oci-cli \
    && /opt/oci-cli/bin/pip install --no-cache-dir oci-cli==3.90.3
ENV PATH=/opt/oci-cli/bin:${PATH}
USER 10001:10001
ENTRYPOINT ["/srv/racetime/.docker/start-production"]
