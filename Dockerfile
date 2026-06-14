FROM python:3.14-alpine

# Version is single-sourced from git tags (hatch-vcs). The build context does
# not include .git, so pass the resolved version in via SETUPTOOLS_SCM_PRETEND_VERSION
# (which hatch-vcs honors). Defaults to 0.0.0 for a bare `docker build`.
ARG VERSION=0.0.0

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY mail2task ./mail2task
RUN SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" pip install --no-cache-dir .

RUN adduser -D -H mail2task
USER mail2task

# OCI image annotations. Static values are baked in; version/revision/created
# vary per build and are passed in (the CI workflow supplies them, and
# docker/metadata-action overrides them with authoritative values on push).
ARG REVISION=""
ARG CREATED=""
LABEL org.opencontainers.image.title="mail2task" \
      org.opencontainers.image.description="Poll an IMAP folder, enrich each email with Ollama, and create Todoist tasks." \
      org.opencontainers.image.url="https://github.com/ykgmfq/mail2task" \
      org.opencontainers.image.source="https://github.com/ykgmfq/mail2task" \
      org.opencontainers.image.documentation="https://github.com/ykgmfq/mail2task#readme" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.authors="Dennis M. Pöpperl <free-software@dm-poepperl.de>" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}"

ENTRYPOINT ["mail2task"]
