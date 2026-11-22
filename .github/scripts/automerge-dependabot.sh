#!/usr/bin/env bash
# Enable auto-merge on a Dependabot pull request unless it contains a major update.
# Grouped pull requests hold several updates, so every one of them is checked.
set -euo pipefail

# jq -e exits with 0 only when the filter yields true, so it doubles as the condition.
if jq -e 'any(.[]; .updateType == "version-update:semver-major")' <<< "${UPDATES_JSON}" > /dev/null; then
  echo "Contains a major update; leaving it for manual review."
  exit 0
fi

# Auto-merge waits until the required status checks pass.
gh pr merge --auto --rebase "${PR_URL}"
