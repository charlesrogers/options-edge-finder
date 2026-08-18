#!/usr/bin/env bash
#
# Inner loop of the dead-man's switch (spec A3 Layer 1).
#
# Curls the health endpoint and alerts if it is unhealthy OR if this script
# itself cannot complete. Deliberately dumb: an HTTP status code and an exit
# code, no JSON parsing. That only works because /api/cron/health now returns
# 503 on fail — it used to return 200 with {"status":"fail"} in the body, so the
# previous `curl -sf` one-liner in /etc/cron.d could not detect a failing health
# check at all and would have run green through the entire 4.5-month outage.
#
# Two things this must never do:
#   - exit 0 when it could not determine health. Unknown is not healthy.
#   - exit 0 when it produced an alert it could not deliver. An undeliverable
#     alert is an outage, not a detail.
#
# Install: /usr/local/bin/options-health-check.sh, mode 700, root.

set -uo pipefail

ENV_FILE=/etc/options-copilot.env
LOG=/var/log/options-copilot.log
URL="https://options.imprevista.com/api/cron/health"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

if [ ! -r "$ENV_FILE" ]; then
  log "FATAL: $ENV_FILE missing or unreadable — cannot authenticate or alert"
  exit 1
fi
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

if [ -z "${CRON_SECRET:-}" ]; then
  log "FATAL: CRON_SECRET empty in $ENV_FILE"
  exit 1
fi

BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT

CODE=$(curl -s -o "$BODY" -w '%{http_code}' --max-time 45 \
  -H "Authorization: Bearer ${CRON_SECRET}" "$URL" 2>>"$LOG")
CURL_RC=$?

# A transport failure is indistinguishable from a dead app from out here, and
# both mean the same thing to the operator: nobody is watching the positions.
if [ "$CURL_RC" -ne 0 ]; then
  DETAIL="health endpoint unreachable (curl exit ${CURL_RC})"
  CODE="000"
elif [ "$CODE" = "200" ]; then
  log "OK ${CODE} $(head -c 200 "$BODY")"
  exit 0
else
  DETAIL="health endpoint returned HTTP ${CODE}: $(head -c 400 "$BODY")"
fi

log "FAIL ${DETAIL}"

DELIVERED=0

if [ -n "${DISCORD_WEBHOOK:-}" ]; then
  if curl -sf -m 20 -H 'Content-Type: application/json' -X POST "$DISCORD_WEBHOOK" \
      -d "{\"embeds\":[{\"title\":\"🚨 Options Copilot health check FAILED\",\"color\":16711680,\"description\":$(printf '%s' "$DETAIL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"footer\":{\"text\":\"hetzner inner loop — /usr/local/bin/options-health-check.sh\"}}]}" \
      >/dev/null 2>>"$LOG"; then
    DELIVERED=1
  else
    log "ALERT UNDELIVERED: Discord webhook post failed"
  fi
else
  log "ALERT UNDELIVERED: DISCORD_WEBHOOK unset in $ENV_FILE"
fi

if [ -n "${PUSHOVER_TOKEN:-}" ] && [ -n "${PUSHOVER_USER:-}" ]; then
  if curl -sf -m 20 -X POST https://api.pushover.net/1/messages.json \
      --data-urlencode "token=${PUSHOVER_TOKEN}" \
      --data-urlencode "user=${PUSHOVER_USER}" \
      --data-urlencode "title=Options Copilot health FAILED" \
      --data-urlencode "message=${DETAIL}" \
      --data-urlencode "priority=1" \
      >/dev/null 2>>"$LOG"; then
    DELIVERED=1
  else
    log "ALERT UNDELIVERED: Pushover post failed"
  fi
else
  log "ALERT UNDELIVERED: PUSHOVER_TOKEN/PUSHOVER_USER unset in $ENV_FILE"
fi

if [ "$DELIVERED" -eq 0 ]; then
  log "CRITICAL: health check failed AND no alert channel worked"
fi
exit 1
