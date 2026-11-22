#!/usr/bin/env bash
# Work out which release tag this run publishes and check it out.
# A tag push publishes that tag; scheduled and manual runs rebuild the newest release tag.
set -euo pipefail

if [ "${GITHUB_REF_TYPE}" = "tag" ]; then
  tag="${GITHUB_REF_NAME}"
else
  tag=$(git tag --list 'v*' --sort=-v:refname | head -n 1)
fi

if [ -z "${tag}" ]; then
  echo "No release tag found; nothing to publish." >&2
  exit 1
fi

git checkout --quiet "${tag}"
revision=$(git rev-parse HEAD)

{
  echo "tag=${tag}"
  echo "version=${tag#v}"
  echo "revision=${revision}"
  echo "short_sha=${revision::7}"
  echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >> "${GITHUB_OUTPUT}"
