# Server-side reliability pieces

Everything here is installed on the Hetzner box (95.216.205.160) by hand — it is
not built by CI, and it is not in any Docker image. It lives in git so the next
person can see what is on the server without SSHing in to find out.

| File | Installed at | Mode |
|---|---|---|
| `options-health-check.sh` | `/usr/local/bin/options-health-check.sh` | 700 |
| `app-cron.sh` | `/usr/local/bin/app-cron.sh` | 700 |
| `options-copilot.env.example` | `/etc/options-copilot.env` (values filled in) | 600 |

`/etc/ply-cron.env` and `/etc/dayscore-cron.env` follow the same pattern for the
other two apps that had tokens in `/etc/cron.d/coolify-apps` (mode 0644).

## Why the env files exist

`/etc/cron.d/coolify-apps` is world-readable on a host running 50+ containers,
and it held three apps' bearer tokens in plaintext. The wrapper scripts read
them from 0600 files instead. They also log every call and alert on failure —
the lines they replaced ended in `> /dev/null 2>&1`, which is how PLY's match
delivery ran 46 consecutive 401s without anyone noticing.

## Still to install

`/usr/local/bin/options-monitor.sh` — the Python position monitor running on
this box as the primary path. Blocked on `PUSHOVER_TOKEN` / `PUSHOVER_USER` in
`/etc/options-copilot.env`: a monitor that runs but cannot deliver an alert is
the same failure as one that does not run, wearing a green check.
