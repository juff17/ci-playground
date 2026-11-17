#!/usr/bin/env bash
# Fails a release job on purpose: always when FAIL_AT names it, or on the first
# attempt when FLAKY_AT does. Otherwise does nothing, and the job goes on.
set -euo pipefail

step=$1

if [ "${FAIL_AT:-none}" = "$step" ]; then
  case $step in
    build) echo "error: package metadata is invalid: version 'next' is not PEP 440" ;;
    test) echo "FAIL: test_release_smoke (AssertionError: 41 != 42)" ;;
    *) echo "error: deploy to $step failed: health check returned 503 after 5 tries" ;;
  esac
  exit 1
fi

if [ "${FLAKY_AT:-none}" = "$step" ] && [ "${GITHUB_RUN_ATTEMPT:-1}" = "1" ]; then
  echo "Error: connect ETIMEDOUT 140.82.112.4:443 while pulling registry layer (network unreachable)"
  exit 1
fi
