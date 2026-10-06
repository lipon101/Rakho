#!/usr/bin/env bash
# Gunicorn entrypoint that makes Prometheus metrics correct under multiple workers.
#
# Why this file exists at all: gunicorn runs more than one worker by default, and
# the default Prometheus registry is *per process*. Two workers therefore publish
# two independent counters, and a scrape reaches whichever worker answers it ---
# so the dashboard reports roughly half the real traffic, with nothing on screen
# to suggest that half the numbers are missing. That failure looks exactly like
# "traffic dropped", which is the worst possible way for a monitoring bug to
# present itself.
#
# ``prometheus_client.multiprocess`` fixes it by having every worker write into a
# shared directory that the scrape aggregates. The catch, and the reason this is
# a script rather than one environment variable: **the directory must be empty
# when the workers start**. The multiprocess collector reads any file it finds
# there as a live metric file, so files left by a previous boot are replayed as
# current data --- stale counters, stale gauges, and a p99 that never resets.
#
# So: clear the directory, create it, then exec gunicorn.

set -euo pipefail

PROM_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus}"

# Clear before starting. A container restart reuses /tmp on some platforms, so
# this is not theoretical --- it is the difference between a correct p95 and a
# p95 averaged with traffic from a deploy that happened yesterday.
if [ -d "$PROM_DIR" ]; then
  rm -f "$PROM_DIR"/*
else
  mkdir -p "$PROM_DIR"
fi

export PROMETHEUS_MULTIPROC_DIR="$PROM_DIR"

# ``exec`` so gunicorn replaces this shell and receives SIGTERM directly. Without
# it, the platform's stop signal reaches the shell and gunicorn is killed rather
# than asked to finish in-flight requests.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
