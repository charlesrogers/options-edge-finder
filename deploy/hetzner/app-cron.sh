#!/usr/bin/env bash
#
# Generic authenticated cron caller.
#
# Exists so bearer tokens stop living in /etc/cron.d/coolify-apps, which is mode
# 0644 — world-readable on a box running 50+ containers. That file held three
# apps' tokens in plaintext (options, PLY, dayscore).
#
# Usage:  app-cron.sh <env-file> <url>
#   env-file must define CRON_SECRET, and may define DISCORD_WEBHOOK.
#
# Unlike the `curl -sf ... >/dev/null 2>&1` lines it replaces, a failure here is
# logged and, if a webhook is configured, alerted. PLY's match delivery ran 46
# consecutive 401s into /dev/null before GitHub disabled it and real users
# stopped getting matches.

set -uo pipefail

ENV_FILE="${1:?usage: app-cron.sh <env-file> <url>}"
URL="${2:?usage: app-cron.sh <env-file> <url>}"
LOG="${CRON_LOG:-/var/log/app-cron.log}"
NAME="$(basename "$ENV_FILE" .env)"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [$NAME] $*" >> "$LOG"; }

if [ ! -r "$ENV_FILE" ]; then
  log "FATAL: $ENV_FILE missing or unreadable"
  exit 1
fi
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

if [ -z "${CRON_SECRET:-}" ]; then
  log "FATAL: CRON_SECRET empty in $ENV_FILE"
  exit 1
fi

BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT
CODE=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 120 \
  -H "Authorization: Bearer ${CRON_SECRET}" "$URL" 2>>"$LOG")
RC=$?

if [ "$RC" -eq 0 ] && [ "$CODE" -ge 200 ] && [ "$CODE" -lt 300 ]; then
  log "OK ${CODE} ${URL}"
  exit 0
fi

DETAIL="${URL} -> HTTP ${CODE} (curl rc ${RC}): $(head -c 300 "$BODY")"
log "FAIL ${DETAIL}"

if [ -n "${DISCORD_WEBHOOK:-}" ]; then
  curl -sf -m 20 -H 'Content-Type: application/json' -X POST "$DISCORD_WEBHOOK" \
    -d "{\"embeds\":[{\"title\":\"🚨 cron failed: ${NAME}\",\"color\":16711680,\"description\":$(printf '%s' "$DETAIL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}]}" \
    >/dev/null 2>>"$LOG" || log "ALERT UNDELIVERED: Discord post failed"
else
  log "ALERT UNDELIVERED: DISCORD_WEBHOOK unset in $ENV_FILE"
fi
exit 1
